# -*- coding: utf-8 -*-
###################################################################################
# Added to enable code completion in IDE's.
if 0:
    from gluon import *  # @UnusedWildImport
    from gluon import auth, request, session
    from applications.baadal.models import *  # @UnusedWildImport
    from db import oauth_login
    import gluon
    global auth; auth = gluon.tools.Auth()
###################################################################################
from auth_user import AUTH_TYPE_OAUTH
from gluon import current  # @Reimport
from helper import config, get_constant
from maintenance import BAADAL_STATUS_UP

current.auth_type = config.get("AUTH_CONF","auth_type")

def user():
    """
    exposes:
    http://..../[app]/default/user/login 
    http://..../[app]/default/user/logout
    http://..../[app]/default/user/register
    http://..../[app]/default/user/profile
    http://..../[app]/default/user/retrieve_password
    http://..../[app]/default/user/change_password
    use @auth.requires_login()
        @auth.requires_membership('group name')
    to decorate functions that need access control
	"""
    
    if current.auth_type == AUTH_TYPE_OAUTH:
        auth.settings.login_form = oauth_login
    return dict(form=auth())


def index():
    if auth.is_logged_in():
        if get_constant('baadal_status') != BAADAL_STATUS_UP:
            if not is_moderator():
                redirect(URL(r=request,c='default', f='user/logout'))
            session.flash='Baadal is in Maintenance Mode'
    return dict(request=request)

def contact():
    return dict()

def team():
    return dict()

def faq():
    return dict()

def about():
    return dict()

def solutions():
    return dict()

def client():
    return dict()

def pricing():
    return dict()

def gallery():
    return dict()

def infrastructure():
    return dict()

def error():
    return dict(error=request.vars['error'])

def page_under_construction():
    return dict()

