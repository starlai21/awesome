#!/usr/bin/env python3


__author__ = 'Michael Liao'

' url handlers '

import re, time, json, logging, hashlib, base64, asyncio
from aiohttp import web
from apis import APIValueError, APIResourceNotFoundError,APIError,APIPermissionError,Page
from coroweb import get, post

import markdown2
from models import User, Comment, Blog, next_id
from config import configs
COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret


def user2cookie(user, max_age):
    '''
    Generate cookie str by user.
    '''
    # build cookie string by: id-expires-sha1
    expires = str(int(time.time() + max_age))
    s = '%s-%s-%s-%s' % (user.id, user.passwd, expires, _COOKIE_KEY)
    L = [user.id, expires, hashlib.sha1(s.encode('utf-8')).hexdigest()]
    return '-'.join(L)

@asyncio.coroutine
def cookie2user(cookie_str):
    '''
    Parse cookie and load user if cookie is valid.
    '''
    if not cookie_str:
        return None
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        uid, expires, sha1 = L
        if int(expires) < time.time():
            return None
        user = yield from User.find(uid)
        if user is None:
            return None
        s = '%s-%s-%s-%s' % (uid, user.passwd, expires, _COOKIE_KEY)
        if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():
            logging.info('invalid sha1')
            return None
        user.passwd = '******'
        return user
    except Exception as e:
        logging.exception(e)
        return None

@get('/')
@asyncio.coroutine
def index(request):
    summary = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    # blogs = [
    #     Blog(id='1', name='Test Blog', summary=summary, created_at=time.time()-120),
    #     Blog(id='2', name='Something New', summary=summary, created_at=time.time()-3600),
    #     Blog(id='3', name='Learn Swift', summary=summary, created_at=time.time()-7200)
    # ]
    blogs=yield from Blog.findAll(orderBy='created_at desc')
    return {
        '__template__': 'blogs.html',
        'blogs': blogs,
        '__user__':request.__user__
    }

@get('/api/users')
@asyncio.coroutine
def api_get_users():
    users = yield from User.findAll(orderBy='created_at desc')
    for u in users:
        u.passwd = '******'
    return dict(users=users)

@get('/test')
@asyncio.coroutine
def test(request):
    users=yield from User.findAll()
    return {
        '__template__':'test.html',
        'users':users

    }

@get('/register')
def register():
    return {
        '__template__': 'register.html'
    }

@get('/signin')
def signin():
    return {
        '__template__': 'signin.html'
    }

@post('/api/authenticate')
@asyncio.coroutine
def authenticate(*, email, passwd):
    if not email:
        raise APIValueError('email', 'Invalid email.')
    if not passwd:
        raise APIValueError('passwd', 'Invalid password.')
    users = yield from User.findAll('email=?', [email])
    if len(users) == 0:
        raise APIValueError('email', 'Email not exist.')
    user = users[0]
    # check passwd:
    sha1 = hashlib.sha1()
    sha1.update(user.id.encode('utf-8'))
    sha1.update(b':')
    sha1.update(passwd.encode('utf-8'))
    if user.passwd != sha1.hexdigest():
        raise APIValueError('passwd', 'Invalid password.')
    # authenticate ok, set cookie:
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.passwd = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r

@get('/signout')
def signout(request):
    referer = request.headers.get('Referer')
    r = web.HTTPFound(referer or '/')
    r.set_cookie(COOKIE_NAME, '-deleted-', max_age=0, httponly=True)
    logging.info('user signed out.')
    return r

_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1 = re.compile(r'^[0-9a-f]{40}$')

@post('/api/users')
@asyncio.coroutine
def api_register_user(*, email, name, passwd):
    if not name or not name.strip():
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    if not passwd or not _RE_SHA1.match(passwd):
        raise APIValueError('passwd')
    users = yield from User.findAll('email=?', [email])
    if len(users) > 0:
        raise APIError('register:failed', 'email', 'Email is already in use.')
    uid = next_id()
    sha1_passwd = '%s:%s' % (uid, passwd)
    user = User(id=uid, name=name.strip(), email=email, passwd=hashlib.sha1(sha1_passwd.encode('utf-8')).hexdigest(), image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
    yield from user.save()
    # make session cookie:
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.passwd = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r

@get('/manage/blogs/create')                        #创建新blog
def manage_create_blog(request):
    return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs',
        '__user__':request.__user__
    }

@get('/manage/blogs/edit')                            #修改blog
def edit_blog(*,id,request):
    return {
        '__template__':'manage_blog_edit.html',
        'id':id,
        '__user__':request.__user__,
        'action':'/api/blogs/%s'%id
    }

@post('/api/blogs/{id}')                        #修改blog api.
@asyncio.coroutine
def api_edit_blog(*,id,name,summary,content,request):
    check_admin(request)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog= yield from Blog.find(id)
    blog.name=name.strip()
    blog.summary=summary.strip()
    blog.content=content.strip()
    yield from blog.update()
    return blog

@get('/manage/comments')                        #管理comments
def manage_comments(*,page='1',request):
    return {
        '__template__':'manage_comments.html',
        'page_index':get_page_index(page),
        '__user__':request.__user__
    }
    
@post('/api/comments/{id}/delete')              #delete comment api
@asyncio.coroutine
def api_delete_comment(*,id,request):
    check_admin(request)
    comment=yield from Comment.find(id)
    yield from comment.remove()
    return dict(id=id)   

@get('/api/comments')                              #comments  api
@asyncio.coroutine
def api_get_comments(*,page='1'):
    page_index=get_page_index(page)
    num=yield from Comment.findNumber('count(id)')
    p=Page(num,page_index)
    if num==0:
        return dict(page=p,comments=())
    comments=yield from Comment.findAll(orderBy='created_at desc',limit=(p.offset,p\
        .limit))
    logging.info('Test',comments)
    return dict(page=p,comments=comments)





@post('/api/blogs/{id}/comments')                       #创建comment api.
@asyncio.coroutine
def api_add_comment(*,id,content,request):
    user=request.__user__
    if user==None:
        raise APIPermissionError('Please signin first.')
    if not content or not content.strip():
        raise APIValueError('comment_content','content cannot be empty.')
    comment=Comment(user_id=request.__user__.id,blog_id=id,user_name=request.__user__.name,\
        user_image=request.__user__.image,content=content)
    yield from comment.save()
    return comment

@get('/manage/users')
def get_users(*,page='1',request):
    return{  
        'page_index':get_page_index(page),
        '__user__':request.__user__,
        '__template__':'manage_users.html'
    }

@get('/api/users')
@asyncio.coroutine
def api_get_users(*,page,request):
    check_admin(request)
    page_index=get_page_index(page)
    num=yield from User.findNumber('count(id)')
    p=Page(num,page_index)
    if num==0:
        return dict(page=p,users=())
    users=yield from User.findAll(orderBy='created_at desc',limit=(p.offset,p.limit))
    return dict(page=p,users=users)

@post('/api/blogs/{id}/delete')                         #删除blog api.
@asyncio.coroutine
def api_delete_blog(*,id,request):
    check_admin(request)
    blog=yield from Blog.find(id)
    yield from blog.remove()
    return dict(id='success.')

@get('/blog/{id}')                      #查看blog
@asyncio.coroutine
def get_blog(*,id,request):
    blog = yield from Blog.find(id)
    comments = yield from Comment.findAll('blog_id=?', [id], orderBy='created_at desc')
    for c in comments:
        c.html_content = text2html(c.content)
    blog.html_content = markdown2.markdown(blog.content)
    return {
        '__template__': 'blog.html',
        'blog': blog,
        'comments': comments,
        '__user__':request.__user__
    }


@get('/api/blogs/{id}')                                         #创建新blog或者编辑完成后用于跳转到该blog
@asyncio.coroutine
def api_get_blog(*, id):
    blog = yield from Blog.find(id)
    return blog



@post('/api/blogs')
@asyncio.coroutine                                              #保存blog
def api_create_blog(request, *, name, summary, content):
    check_admin(request)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog = Blog(user_id=request.__user__.id, user_name=request.__user__.name, user_image=request.__user__.image, name=name.strip(), summary=summary.strip(), content=content.strip())
    yield from blog.save()
    return blog

def check_admin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()

def get_page_index(page_str):
    p = 1
    try:
        p = int(page_str)
    except ValueError as e:
        pass
    if p < 1:
        p = 1
    return p

def text2html(text):
    lines = map(lambda s: '<p>%s</p>' % s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), filter(lambda s: s.strip() != '', text.split('\n')))
    return ''.join(lines)

@get('/api/blogs')
@asyncio.coroutine                                                  #打开管理blogs时请求的url,返回所有blogs和页码
def api_blogs(*, page='1'):
    page_index = get_page_index(page)
    num = yield from Blog.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, blogs=())
    blogs = yield from Blog.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, blogs=blogs)

@get('/manage/blogs')                                               # 管理全部blogs（edit,delete）            
def manage_blogs(*, page='1',request):
    return {
        '__template__': 'manage_blogs.html',
        'page_index': get_page_index(page),
        '__user__':request.__user__
    }