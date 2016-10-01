import asyncio, os, inspect, logging, functools

from urllib import parse

from aiohttp import web

from apis import APIError

#get 和 post 为修饰方法,主要是为对象上加上'__method__'和'__route__'属性
#为了把我们定义的url实际处理方法，以get请求或post请求区分
def get(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator

#关于inspect.Parameter 的  kind 类型有5种：
#POSITIONAL_ONLY        只能是位置参数
#POSITIONAL_OR_KEYWORD  可以是位置参数也可以是关键字参数
#VAR_POSITIONAL         相当于是 *args
#KEYWORD_ONLY           关键字参数且提供了key，相当于是 *,key
#VAR_KEYWORD            相当于是 **kw

#如果url处理函数需要传入关键字参数，且默认是空得话，获取这个key
def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)   
    return tuple(args)

#如果url处理函数需要传入关键字参数，获取这个key
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)   
    return tuple(args)

#如果url处理函数需要传入关键字参数，返回True
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

#如果url处理函数的参数是**kw，返回True
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

##如果url处理函数的参数是request，返回True
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    
    return found

#RequestHandler目的就是从URL函数中分析其需要接收的参数，从request中获取必要的参数，调用URL函数
class RequestHandler(object):
    """docstring for RequestHandler"""
    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        #下面的一系列是为了检测url处理函数的参数类型
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_arg = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    @asyncio.coroutine
    def  __call__(self, request):
        kw = None
        logging.info(' %s : has_request_arg = %s,  has_var_kw_arg = %s, has_named_kw_args = %s, get_named_kw_args = %s, get_required_kw_args = %s ' % (__name__, self._has_request_arg, self._has_var_kw_arg, self._has_named_kw_arg,self._named_kw_args ,self._required_kw_args))
        #如果处理函数需要传入特定key的参数或者可变参数的话
        if self._has_var_kw_arg or self._has_named_kw_arg or self._required_kw_args:
            #如果是post请求，则读请求的body
            if request.method == 'POST':
                #如果request的头中没有content-type，则返回错误描述
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type')
                #字符串全部转为小写
                ct = request.content_type.lower()
                #如果是'application/json'类型
                if ct.startswith('application/json'):
                    #把request的body，按json的方式输出为一个字典
                    params = yield from request.json()
                    #解读出错或params不是一个字典，则返回错误描述
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest('JSON Body must be object')
                    #保存这个params
                    kw = params
                #如果是'application/x-www-form-urlencoded'，或'multipart/form-data'，直接读出来并保存
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = yield from request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type:%s' % request.content_type)
            #如果是get请求，则读请求url字符串
            if request.method == 'GET':
                #看url有没有参数，即？后面的字符串
                qs = request.query_string
                logging.info('qs = %s' % qs)
                #如果有的话，则把参数以键值的方式存起来赋值给kw
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        #如果kw为空得话，kw设置为request.match_info
        if kw is None:
            kw = dict(**request.match_info)
            logging.info(request.match_info)
            logging.info('kw = %s' % kw)
        else:
            #如果kw有值得话
            #如果处理方法需要传入 **kw,且需要传入关键字参数
            if not self._has_var_kw_arg and self._named_kw_args:
                copy =  dict()
                #从kw中筛选出url处理方法需要传入的参数对
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            #从match_info中筛选出url处理方法需要传入的参数对
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)  
                kw[k] = v
        #如果参数需要传'request'参数，则把request实例传入
        if self._has_request_arg:
            kw['request'] = request

        #如果参数有默认为None的关键子参数，遍历一下kw，如果kw中没有这个key，抛错
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            #对url进行处理
            r = yield from self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

#添加静态页面的路径
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

def add_route(app, fn):
    #获取'__method__'和'__route__'属性，如果有空则抛出异常
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    #判断fn是不是协程(即@asyncio.coroutine修饰的) 并且 判断是不是fn 是不是一个生成器(generator function)
    if not asyncio.iscoroutine(fn) and not inspect.isgeneratorfunction(fn):
        #都不是的话，强行修饰为协程
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s (%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    #正式注册为相应的url处理方法
    #处理方法为RequestHandler的自省函数 '__call__'
    app.router.add_route(method, path, RequestHandler(app, fn))

#自动搜索传入的module_name的module的处理函数
def add_routes(app, module_name):
    #检查传入的module_name是否有'.'
    n = module_name.rfind('.')
    logging.info('n = %s', n)
    #没有'.',则传入的是module名
    #__import__(module)其实就是 import module
    if n == (-1):
        mod = __import__(module_name, globals(), locals())
        logging.info('globals = %s', globals()['__name__'])
    else:
        print ('haha')
        # name = module_name[n+1:]
        # mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
        #上面两行是廖大大的源代码，但是把传入参数module_name的值改为'handlers.py'的话走这里是报错的，所以改成了下面这样
        mod = __import__(module_name[:n], globals(), locals())
    #遍历mod的方法和属性,主要是招处理方法
    #由于我们定义的处理方法，被@get或@post修饰过，所以方法里会有'__method__'和'__route__'属性
    for attr in dir(mod):
        #如果是以'_'开头的，一律pass，我们定义的处理方法不是以'_'开头的
        if attr.startswith('_'):
            continue
        #print ('attr = ',attr)
        #获取到非'_'开头的属性或方法
        fn = getattr(mod, attr)
        #取能调用的，说明是方法
        if callable(fn):
            #检测'__method__'和'__route__'属性
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                #如果都有，说明使我们定义的处理方法，加到app对象里处理route中
                add_route(app, fn)
    