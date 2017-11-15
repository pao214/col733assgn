# -*- coding: utf-8 -*-
"""
user_model.py: This model has functions to handle database transaction for 
functionalities that is accessible to users with user role.
"""
###################################################################################
# Added to enable code completion in IDE's.
if 0:
    from gluon import *  # @UnusedWildImport
    from gluon import db,auth,request
    import gluon
    global auth; auth = gluon.tools.Auth()
    from applications.baadal.models import *  # @UnusedWildImport
###################################################################################
from auth_user import fetch_ldap_user, create_or_update_user, AUTH_TYPE_DB
from cont_handler import Container
from datetime import timedelta
from helper import log_exception, get_datetime, get_file_append_mode, config, \
    execute_remote_cmd, sftp_files, get_context_path
from images import getImageProfileList
from log_handler import logger
from nat_mapper import VNC_ACCESS_STATUS_ACTIVE, VNC_ACCESS_STATUS_INACTIVE
import os

def get_my_requests():
    """
    Returns list of request_queue elements requested by authenticated user
    @return: List of requests. 
    @rtype: C{list} 
    """
    requests = db(db.request_queue.requester_id==auth.user.id).select(db.request_queue.ALL)
    return get_pending_request_list(requests)


def get_my_hosted_vm():
    """
    Get list of hosted virtual machines for a user
    @return: List of hosted VMs. 
    @rtype: C{list} 
    """
    vms = db((~db.vm_data.status.belongs(VM_STATUS_IN_QUEUE, VM_STATUS_UNKNOWN)) 
             & (db.vm_data.id==db.user_vm_map.vm_id) 
             & (db.user_vm_map.user_id==auth.user.id)).select(db.vm_data.ALL)

    return get_hosted_vm_list(vms)


def get_my_object_store():
    """get list of object store"""
    
    try:
        object_store = db((~db.object_store_data.status.belongs(VM_STATUS_IN_QUEUE, VM_STATUS_UNKNOWN))
                          & (db.object_store_data.id==db.user_object_map.ob_id)
                          & (db.user_object_map.user_id==auth.user.id)).select(db.object_store_data.ALL)
        return get_my_object_store_list(object_store)
    except:
        logger.debug("Exception occurred: %s " % log_exception())
        l = []
        return l    


def get_my_container():
    """get list of container"""
    container = db((~db.container_data.status.belongs(VM_STATUS_IN_QUEUE, VM_STATUS_UNKNOWN))& (db.container_data.id==db.user_container_map.cont_id)& (db.user_container_map.user_id==auth.user.id)).select(db.container_data.ALL)
    return get_my_container_list(container)
     

def get_configuration_elem(form):
    """
    Generates html component of configuration dropdowns
    This is displayed on 'Request VM' page.
    @rtype: C{None} 
    """    
    templates = db().select(db.template.ALL)
    _label = LABEL(SPAN('Configuration:', ' ', SPAN('*', _class='fld_required'), ' '))

    for template in templates:
        _id = template.id
        select = SELECT(_name='configuration_'+str(_id))
        
        for _config in VM_CONFIGURATION:
            display = str(_config[0]) + ' CPU, ' + str(_config[1]) + 'GB RAM, ' + str(template.hdd) + 'GB HDD'
            value = str(_config[0]) + ',' + str(_config[1]) + ',' + str(template.hdd)
            select.insert(len(select), OPTION(display, _value=value))
            
        #Create TR tag, and insert label and select box
        config_elem = TR(_label,select,TD(),_id='config_row__'+str(_id))
        form[0].insert(2,config_elem)#insert tr element in the form

def set_configuration_elem(form):
    """
    Gets CPU, RAM and HDD information on the basis of selected template, which
    is set individually in the form component.
    This is called on submit of 'Request VM' page.
    @rtype: C{None} 
    """    
    configVal = form.vars.configuration_0 #Default configuration dropdown
    template = form.vars.template_id
    
    # if configuration specific to selected template is available
    if eval('form.vars.configuration_'+str(template)) != None:
        configVal = eval('form.vars.configuration_'+str(template))

    configVal = configVal.split(',')
    
    form.vars.vCPU = int(configVal[0])
    form.vars.RAM = float(configVal[1])*1024
    form.vars.HDD = int(configVal[2])
    if form.vars.extra_HDD == None:
        form.vars.extra_HDD = 0


def validate_approver(form):
    """
    Validate if the approver user belongs to group FACULTY.
    In case user is not a faculty, error is updated in form.
    @rtype: C{None} 
    """    
    faculty_user_name = request.post_vars.faculty_user
    
    faculty_info = get_user_info(faculty_user_name, [FACULTY])
    if faculty_info != None:
        form.vars.owner_id = faculty_info[0]
        form.vars.status = REQ_STATUS_REQUESTED
    else:
        form.errors.faculty_user='Faculty Approver Username is not valid'


def send_remind_faculty_email(req_id):
    req_data = db.request_queue[req_id]
    send_email_to_approver(req_data.owner_id, req_data.requester_id, req_data.request_type, req_data.request_time)


def send_remind_orgadmin_email(req_id):
    req_data = db.request_queue[req_id]
    admins = db((db.user.organisation_id == req_data.requester_id.organisation_id) 
                & (db.user.id == db.user_membership.user_id) 
                & (db.user_membership.group_id == db.user_group.id) 
                & (db.user_group.role == ORGADMIN)).select(db.user.id)
                
    for admin in admins:
        send_email_to_approver(admin.id, req_data.requester_id, req_data.request_type, req_data.request_time)


def get_request_status():
    status = REQ_STATUS_REQUESTED
    if (is_moderator() or is_orgadmin()):
        status = REQ_STATUS_APPROVED
    elif is_faculty():
        status = REQ_STATUS_VERIFIED
    return status


def is_object_store_name_unique(user_set, object_store_name=None, vm_id=None):
    """
    Check if Object Store name is unique for the user.
    This function checks both user's existing object store 
    and pending requests in queue"""
    requests = db(((db.request_queue.owner_id.belongs(user_set)) |
                   (db.request_queue.requester_id.belongs(user_set))) & 
                   (db.request_queue.object_store_name.like(object_store_name))).select()
    
    return False if requests else True


def is_vm_name_unique(user_set, vm_name=None, vm_id=None):
    """
    Check if VM name is unique for the user.
    This function checks both user's existing virtual machine 
    and pending requests in queue"""
    
    if vm_id != None:
        vm_data = db.vm_data[vm_id]
        vm_name = vm_data.vm_name
        
    vms = db((db.vm_data.id == db.user_vm_map.vm_id) & 
             (db.user_vm_map.user_id.belongs(user_set)) & 
             (db.vm_data.vm_name.like(vm_name))).select()
    
    if vms:
        return False

    requests = db(((db.request_queue.owner_id.belongs(user_set)) |
                   (db.request_queue.requester_id.belongs(user_set))) & 
                   (db.request_queue.vm_name.like(vm_name))).select()
    
    return False if requests else True

def is_container_name_unique(user_set, vm_name=None, vm_id=None):
    """
    Check if VM name is unique for the user.
    This function checks both user's existing virtual machine 
    and pending requests in queue"""

    requests = db(((db.request_queue.owner_id.belongs(user_set)) |
                   (db.request_queue.requester_id.belongs(user_set))) & 
                   (db.request_queue.vm_name.like(vm_name))).select()
    
    return False if requests else True

    
def request_object_store_validation(form):
    form.vars.status = get_request_status()
    if is_general_user():
        validate_approver(form)
    else:
        form.vars.owner_id = auth.user.id
    vm_users = request.post_vars.vm_users
    user_list = []
    if vm_users and len(vm_users) > 1:
        for vm_user in vm_users[1:-1].split('|'):
            user_list.append(db(db.user.username == vm_user).select(db.user.id).first()['id'])
    
    if request.post_vars.faculty_user:
        user_list.append(form.vars.owner_id)
    form.vars.collaborators = user_list

    user_set = set(user_list)
    user_set.add(auth.user.id)

    if not is_object_store_name_unique(user_set, form.vars.object_store_name):
        form.errors.object_store_name = 'Object Store name should be unique for the user. Choose another name.'

def request_container_validation(form):
    
    form.vars.status = get_request_status()
    if is_general_user():
        validate_approver(form)
    else:
        form.vars.owner_id = auth.user.id    
    vm_users = request.post_vars.vm_users
    env_vars = request.post_vars.env_var_list
    logger.debug(form.vars)
    
    env_dict= {}
    if env_vars and len(env_vars) > 1:
        for env_var in env_vars[1:-1].split('|'):
            vals = env_var.split("=")
            logger.debug(vals[0])
            if len(vals) == 2:
                logger.debug(vals[1])
                env_dict[vals[0]] = vals[1]
    env_dict['image_profile'] = form.vars.image_profile
    logger.debug(env_dict)
    form.vars.env_vars = env_dict
    user_list = []
    if vm_users and len(vm_users) > 1:
        for vm_user in vm_users[1:-1].split('|'):
            user_list.append(db(db.user.username == vm_user).select(db.user.id).first()['id'])
    
    if request.post_vars.faculty_user:
        user_list.append(form.vars.owner_id)
    form.vars.collaborators = user_list

    user_set = set(user_list)
    user_set.add(auth.user.id)

    '''if not is_container_name_unique(user_set, form.vars.name):
        form.errors.vm_name = "VM name should be unique for the user. Choose another name."'''
        
        
        
        
def request_vm_validation(form):
    set_configuration_elem(form)
    form.vars.status = get_request_status()
    if is_general_user():
        validate_approver(form)
    else:
        form.vars.owner_id = auth.user.id    
    vm_users = request.post_vars.vm_users
    
    user_list = []
    if vm_users and len(vm_users) > 1:
        for vm_user in vm_users[1:-1].split('|'):
            user_list.append(db(db.user.username == vm_user).select(db.user.id).first()['id'])
    
    if request.post_vars.faculty_user:
        user_list.append(form.vars.owner_id)
    form.vars.collaborators = user_list

    user_set = set(user_list)
    user_set.add(auth.user.id)

    if not is_vm_name_unique(user_set, form.vars.vm_name):
        form.errors.vm_name = 'VM name should be unique for the user. Choose another name.'
        

def add_user_verify_row(form, field_name, field_label, verify_function, verify_label = 'Verify', row_id='user_row', is_required=False):

    _input=INPUT(_name=field_name, _id=field_name) # create INPUT
    _link = TD(A(verify_label, _href='#',_onclick=verify_function))
    _label = LABEL(SPAN(field_label, ': ', SPAN('*', _class='fld_required'), ' ')) if is_required else LABEL(SPAN(field_label, ': '))

    field_elem = TR(_label, _input, _link, _id=row_id)
    form[0].insert(-1, field_elem)#insert tr element in the form


def add_faculty_approver(form):

    add_user_verify_row(form, 
                        field_name = 'faculty_user', 
                        field_label = 'Faculty Approver', 
                        verify_function = 'verify_faculty()', 
                        row_id = 'faculty_row',
                        is_required = True)


def add_collaborators(form):

    add_user_verify_row(form, 
                        field_name = 'collaborator', 
                        field_label = 'Collaborators', 
                        verify_function = 'check_collaborator()', 
                        verify_label = 'Add',
                        row_id = 'collaborator_row')

def get_request_object_store_form():
    
    form_fields = ['object_store_name','object_store_size','object_store_type','purpose']

    db.request_queue.request_type.default = Object_Store_TASK_CREATE
    db.request_queue.requester_id.default = auth.user.id
    sd_query = (db.security_domain.visible_to_all == True) | (db.security_domain.org_visibility.contains(auth.user.organisation_id))
    db.request_queue.security_domain.requires = IS_IN_DB(db(sd_query), 'security_domain.id', '%(name)s', zero=None)
    db.request_queue.security_domain.default = 2
    db.request_queue.security_domain.notnull = True
    db.request_queue.template_id.notnull = True

    mark_required(db.request_queue)
    form =SQLFORM(db.request_queue, fields = form_fields, hidden=dict(vm_users='|'))
    get_configuration_elem(form) # Create dropdowns for configuration
    
    if is_general_user(): add_faculty_approver(form)
    
    add_collaborators(form)
    return form

def add_env_var_row(form):

    add_user_verify_row(form, 
                        field_name = 'env_var', 
                        field_label = 'Enviornment Variable', 
                        verify_function = 'check_env_var()', 
                        verify_label = 'Add',
                        row_id = 'env_var_row')
    

def add_image_profile_row(form):
    """
    Generates html component of configuration dropdowns
    """    

    _label = LABEL(SPAN('Template:', ' ', SPAN('*', _class='fld_required'), ' '))

    select = SELECT(_name='image_profile', _id='request_queue_image_profile')
    
    idx=1
    for imageprofile in getImageProfileList():
        display = imageprofile['type']
        value = idx
        idx=idx+1
        select.insert(len(select), OPTION(display, _value=value))
            
    #Create TR tag, and insert label and select box
    template_elem = TR(_label,select,TD())
    form[0].insert(3, template_elem)#insert tr element in the form


def get_request_container_form():    
    form_fields = ['vm_name','RAM','vCPU','purpose','restart_policy']
    db.request_queue.request_type.default = CONTAINER_TASK_CREATE
    db.request_queue.requester_id.default = auth.user.id
    db.request_queue.RAM.notnull = True  
    db.request_queue.vCPU.notnull = True  
    db.request_queue.RAM.requires=IS_INT_IN_RANGE(100,8193)
    db.request_queue.vCPU.requires=IS_INT_IN_RANGE(1,9)
    db.request_queue.vm_name.requires = [IS_MATCH('^[a-zA-Z0-9][\w\-]*$', error_message=NAME_ERROR_MESSAGE), IS_LENGTH(30,1), IS_NOT_IN_DB(db,'container_data.name')]
    mark_required(db.request_queue)
    
    form =SQLFORM(db.request_queue, fields = form_fields, hidden=dict(vm_users='|',env_var_list='|'))
    add_image_profile_row(form)
    add_env_var_row(form)
    
    if is_general_user(): add_faculty_approver(form)    
    add_collaborators(form)
    return form

def get_request_vm_form():
    
    form_fields = ['vm_name','template_id','extra_HDD','purpose', 'security_domain', 'expiry_date']

    db.request_queue.request_type.default = VM_TASK_CREATE
    db.request_queue.requester_id.default = auth.user.id
    sd_query = (db.security_domain.visible_to_all == True) | (db.security_domain.org_visibility.contains(auth.user.organisation_id))
    db.request_queue.security_domain.requires = IS_IN_DB(db(sd_query), 'security_domain.id', '%(name)s', zero=None)
    db.request_queue.security_domain.default = 2
    db.request_queue.security_domain.notnull = True
    db.request_queue.template_id.notnull = True
    db.request_queue.expiry_date.notnull = True
    mark_required(db.request_queue)
    form =SQLFORM(db.request_queue, fields = form_fields, hidden=dict(vm_users='|'))
    get_configuration_elem(form) # Create dropdowns for configuration
    
    if is_general_user(): add_faculty_approver(form)
    
    add_collaborators(form)
    return form


def get_user_info(username, roles=[USER, FACULTY, ORGADMIN, ADMIN]):

    user_query = db((db.user.username == username) 
             & (db.user.id == db.user_membership.user_id)
             & (db.user_membership.group_id == db.user_group.id)
             & (db.user_group.role.belongs(roles)))
    
    user = user_query.select(db.user.ALL).first()
    
    # If user not present in DB
    if not user:
        if current.auth_type != AUTH_TYPE_DB :
            user_info = fetch_ldap_user(username)
            if user_info:
                if [obj for obj in roles if obj in user_info['roles']]:
                    create_or_update_user(user_info, False)
                    user = user_query.select(db.user.ALL).first()
    
    if user:
        if is_moderator() | (user['organisation_id'] == auth.user.organisation_id):
            return (user['id'], (user['first_name'] + ' ' + user['last_name']))


def get_my_task_list(task_status, task_num):
    """Gets list of tasks requested by the user or
       task on any of users's VM"""
    task_query = db((db.task_queue_event.status.belongs(task_status)) 
                    & ((db.task_queue_event.vm_id.belongs(
                            db(auth.user.id == db.user_vm_map.user_id)._select(db.user_vm_map.vm_id))) 
                     | (db.task_queue_event.requester_id == auth.user.id)))
    events = task_query.select(db.task_queue_event.ALL, distinct=True, orderby = ~db.task_queue_event.start_time, limitby=(0,task_num))

    return get_task_list(events)

   
def get_vm_config(vm_id):
    """
    Fetches VM information for the given ID.
    Creates a map of parameters and corresponding display strings 
    
    @param vm_id: VM ID 
    @type vm_id: C{int} 
    @return: Map of vm parameters an its display values. 
    @rtype: C{map} 
    """

    vminfo = get_vm_info(vm_id)
    if not vminfo : return
    
    vm_info_map = {'id'               : str(vminfo.vm_data.id),
                   'name'             : str(vminfo.vm_data.vm_name),
                   'hdd'              : str(vminfo.vm_data.HDD)+' GB' + ('+ ' + str(vminfo.vm_data.extra_HDD) + ' GB' if vminfo.vm_data.extra_HDD!=0 else ''),
                   'ram'              : str(vminfo.vm_data.RAM) + ' MB',
                   'vcpus'            : str(vminfo.vm_data.vCPU) + ' CPU',
                   'status'           : get_vm_status(vminfo.vm_data.status),
                   'os_type'          : str(vminfo.template.os_name) + ' ' + str(vminfo.template.os_version) + ' ' + str(vminfo.template.os_type) + ' ' + str(vminfo.template.arch),
                   'purpose'          : str(vminfo.vm_data.purpose),
                   'private_ip'       : str(vminfo.vm_data.private_ip.private_ip),
                   'public_ip'        : str(vminfo.vm_data.public_ip.public_ip) if vminfo.vm_data.public_ip else PUBLIC_IP_NOT_ASSIGNED,
                   'snapshot_flag'    : int(vminfo.vm_data.snapshot_flag),
                   'security_domain'  : str(vminfo.vm_data.security_domain.name)}

    if is_moderator():
        vm_info_map.update({'host' : str(vminfo.vm_data.host_id.host_ip.private_ip)})
    
    #vnc_info = db((db.vnc_access.vm_id == vm_id) & (db.vnc_access.status == VNC_ACCESS_STATUS_ACTIVE)).select()
    #if vnc_info:
    #    vm_info_map.update({'vnc_ip' : str(vnc_info[0].vnc_server_ip), 'vnc_port' : str(vnc_info[0].vnc_source_port)})

    return vm_info_map  


def get_cont_config(cont_id):
    """
    Fetches VM information for the given ID.
    Creates a map of parameters and corresponding display strings 
    
    @param vm_id: VM ID 
    @type vm_id: C{int} 
    @return: Map of vm parameters an its display values. 
    @rtype: C{map} 
    """

    cont_info = db.container_data[cont_id]
    if not cont_info : return
    
    container = Container(cont_info.UUID);
    container.updatedetails()
    logger.debug("IN get_cont_config")
    
    if container:
        cont_details = container.properties
        logger.debug(cont_details)
        cont_created = cont_details['Created'] #(datetime.datetime.fromtimestamp(cont_details1['Created'])).strftime('%A %d, %b %Y %H:%M')
        cont_command = cont_details['Cmd']
        cont_ports = cont_details['Ports'] if cont_details['Ports'] else {}
        cont_status = cont_details['State']
        cont_env = cont_details['Environment']
        exec_ids = cont_details['ExecIDs']
    else:
        cont_created = "-"
        cont_command = "-"
        cont_ports = [{u'IP': u'0.0.0.0', u'Type': u'', u'PublicPort': 0, u'PrivatePort': 0}]
        cont_status = "Invalid"
        cont_env = cont_info.env_vars
    
    cont_info_map = {'id'           : cont_info.id,
                   'name'           : cont_info.name,
                   'RAM'            : str(round((cont_info.RAM/1024.0),2)) + ' GB',
                   'vcpus'          : str(cont_info.vCPU) + ' CPU',
                   'env_vars'       : cont_env ,
                   'template'       : str(cont_info.image_profile) ,
                   'restart_policy' : str(cont_info.restart_policy) ,
                   'owner'          : cont_info.owner_id.first_name + ' ' + cont_info.owner_id.last_name if cont_info.owner_id > 0 else 'System User',
                   'purpose'        : '-' if cont_info.purpose == '' else cont_info.purpose,
                   'uuid'           : cont_info.UUID,
                   'created'        : cont_created,
                   'command'        : cont_command,
                   'ports'          : cont_ports,
                   'status'         : cont_status,
                   'ExecIds' 		: exec_ids}


    return cont_info_map  


def get_container_uuid(cont_id):
    cont_info = db.container_data[cont_id]
    if not cont_info:
        return None
    else:
        return cont_info.UUID

def get_container_logs(cont_id):
    
    cont_info = db.container_data[cont_id]
    if not cont_info : return
    
    container = Container(cont_info.UUID,setProp=False);
    return container.logs()

def get_container_archive(cont_id,file_path):
    cont_info = db.container_data[cont_id]
    if not cont_info : 
        return None
    
    container = Container(cont_info.UUID,setProp=False);
    return container.get_archive(file_path)

def get_container_archive_wd(cont_id):
    cont_info = db.container_data[cont_id]
    if not cont_info : 
        return None
    
    container = Container(cont_info.UUID);
    return container.get_archive(container.properties['WorkingDir'])
    
def get_container_stats(cont_uuid):
    
    container = Container(cont_uuid,setProp=False);
    return container.stats()

def get_container_execsession(cont_uuid):
    container = Container(cont_uuid,setProp=False);
    return container.execidgenerator()

def get_container_execresize(cont_uuid,cont_session,height,width):
    container = Container(cont_uuid,setProp=False);
    container.execresize(cont_session,height,width);

def get_container_top(cont_id,pid_args='aux'):
    cont_info = db.container_data[cont_id]
    if not cont_info : return
    
    container = Container(cont_info.UUID,setProp=False);
    return container.top(pid_args)
    
def get_container_upload_data(cont_uuid,file_path,file_data):
    container = Container(cont_uuid,setProp=False);
    return container.upload(file_path,file_data);


def get_vpn_user_details():
    user_info=db((db.user.id==auth.user.id)).select(db.user.ALL)
    logger.debug("userinfo"+ str(user_info))
    for info in user_info:
        user_details={'username':info['username'],
         'first_name':info['first_name'],
          'last_name':info['last_name']}
    return user_details


#request vpn function will fire up the script for vpn request and copy the key to controller
#in vpn_ip and passwd you need to supply vpn server ip and passwd
def request_vpn():
    user_info=get_vpn_user_details()
    logger.debug(type(user_info))
    user_name=user_info['username']
    cmd="./vpn_client_creation.sh "+ str(user_name)
    #vpn_ip=""
    vpn_ip=config.get("VPN_CONF","vpn_server_ip")
    vpn_key_path=config.get("VPN_CONF","vpn_key_path")

    try:
        var = execute_remote_cmd(vpn_ip, 'root',cmd, ret_list=True)
        filepath=vpn_key_path+str(user_name)+"_baadalVPN.tar"
        localpath = os.path.join(get_context_path(), 'private/VPN/' + str(user_name) +"_baadalVPN.tar")
        sftp_files(vpn_ip, 'root', filepath, localpath)

        if  "false" in str(var):
            return 1
        elif "true" in str(var):
            return 3
    #transfer_vpn_files(user_name,vpn_ip,password)
    except Exception:
        return 2

def get_vm_user_list(vm_id) :		
    vm_users = db((vm_id == db.user_vm_map.vm_id) & (db.user_vm_map.user_id == db.user.id)).select(db.user.ALL)
    user_id_lst = []
    for vm_user in vm_users:
        user_id_lst.append(vm_user)
    return user_id_lst


def get_cont_user_list(cont_id) :        
    cont_users = db((cont_id == db.user_container_map.cont_id) & (db.user_container_map.user_id == db.user.id)).select(db.user.ALL)
    user_id_lst = []
    for cont_user in cont_users:
        user_id_lst.append(cont_user)
    return user_id_lst


def is_request_in_queue(vm_id, task_type, snapshot_id=None):
    """
    Generic function to check if for a given VM, task of given type is 
    already present in task_queue table"""
    #Check task_queue table
    task_data =  db((db.task_queue.task_type == task_type) 
                   & db.task_queue.status.belongs(TASK_QUEUE_STATUS_PENDING, TASK_QUEUE_STATUS_PROCESSING)).select()

    for task in task_data:
        params = task.parameters
        if int(params['vm_id']) == int(vm_id):
            if snapshot_id != None:
                if params['snapshot_id'] == snapshot_id:
                    return True
            else:
                return True
        
    #Check if request is present in request_queue table
    _request = db((db.request_queue.parent_id == vm_id) & (db.request_queue.request_type == task_type) 
               & db.request_queue.status.belongs(REQ_STATUS_REQUESTED, REQ_STATUS_VERIFIED, REQ_STATUS_APPROVED)).select()

    return True if _request else False


def check_snapshot_limit(vm_id):
    snapshots = db((db.snapshot.vm_id == vm_id) & (db.snapshot.type == SNAPSHOT_USER)).count()
    logger.debug("No of snapshots are " + str(snapshots))
    if snapshots < SNAPSHOTTING_LIMIT:
        return True
    else:
        return False


def check_vm_template_limit(vm_id):
    vm_data = db.vm_data[vm_id]
    if vm_data.saved_template != None:
        return False
    
    return True


def get_clone_vm_form(vm_id):
    vm_data = db.vm_data[vm_id]
    
    clone_name = vm_data.vm_name + '_clone'
    cnt = 1;
    while(db.request_queue(vm_name=(clone_name+str(cnt)))):
        cnt = cnt+1
    
    db.request_queue.parent_id.default = vm_data.id
    db.request_queue.vm_name.default = clone_name + str(cnt)
    db.request_queue.HDD.default = vm_data.HDD
    db.request_queue.RAM.default = vm_data.RAM
    db.request_queue.vCPU.default = vm_data.vCPU
    db.request_queue.request_type.default = VM_TASK_CLONE
    db.request_queue.status.default = get_request_status()
    db.request_queue.requester_id.default = auth.user.id
    db.request_queue.owner_id.default = vm_data.owner_id
    db.request_queue.security_domain.default = vm_data.security_domain
    db.request_queue.clone_count.requires = IS_INT_IN_RANGE(1,101)
    db.request_queue.vm_name.writable = False
    form_fields = ['vm_name', 'clone_count', 'purpose']
    
    form =SQLFORM(db.request_queue, fields = form_fields)
    return form    


def get_attach_extra_disk_form(vm_id):

    vm_data = db.vm_data[vm_id]
    
    db.request_queue.parent_id.default = vm_data.id
    db.request_queue.vm_name.default = vm_data.vm_name
    db.request_queue.RAM.default = vm_data.RAM
    db.request_queue.vCPU.default = vm_data.vCPU
    db.request_queue.HDD.default = vm_data.HDD
    db.request_queue.extra_HDD.default = vm_data.extra_HDD
    db.request_queue.request_type.default = VM_TASK_ATTACH_DISK
    db.request_queue.status.default = get_request_status()
    db.request_queue.requester_id.default = auth.user.id
    db.request_queue.owner_id.default = vm_data.owner_id
    db.request_queue.attach_disk.requires = IS_INT_IN_RANGE(1,101)
    db.request_queue.vm_name.writable = False
    db.request_queue.HDD.writable = False
    db.request_queue.extra_HDD.writable = False

    form_fields = ['vm_name', 'HDD', 'extra_HDD', 'attach_disk', 'purpose']
    
    form =SQLFORM(db.request_queue, fields = form_fields)
    return form    


def get_edit_vm_config_form(vm_id):
    
    vm_data = db.vm_data[vm_id]
    db.request_queue.parent_id.default = vm_data.id
    db.request_queue.vm_name.default = vm_data.vm_name
    db.request_queue.RAM.default = vm_data.RAM
    db.request_queue.RAM.requires = IS_IN_SET(VM_RAM_SET, zero=None)
    db.request_queue.vCPU.default = vm_data.vCPU
    db.request_queue.vCPU.requires = IS_IN_SET(VM_vCPU_SET, zero=None)
    db.request_queue.HDD.default = vm_data.HDD
    db.request_queue.public_ip.default = (vm_data.public_ip != None)
    db.request_queue.security_domain.default = vm_data.security_domain
    db.request_queue.request_type.default = VM_TASK_EDIT_CONFIG
    db.request_queue.status.default = get_request_status()
    db.request_queue.requester_id.default = auth.user.id
    db.request_queue.owner_id.default = vm_data.owner_id
    _query = (db.security_domain.visible_to_all == True) | (db.security_domain.org_visibility.contains(vm_data.requester_id.organisation_id))
    db.request_queue.security_domain.requires = IS_IN_DB(db(_query), 'security_domain.id', '%(name)s', zero=None)
    
    form_fields = ['vm_name', 'RAM', 'vCPU', 'public_ip', 'security_domain','purpose']
    form = SQLFORM(db.request_queue, fields = form_fields)

    return form

def edit_vm_config_validation(form):
    
    vm_id = request.args[0]
    vm_data = db.vm_data[vm_id]
    
    curr_public_ip = False if vm_data.public_ip == None else True
    new_public_ip = True if form.vars.public_ip else False
    
    if ((long(form.vars.vCPU) == long(vm_data.vCPU)) & 
        (long(form.vars.security_domain) == long(vm_data.security_domain)) & 
        (long(form.vars.RAM) == long(vm_data.RAM)) & 
        (new_public_ip == curr_public_ip)):
        
        form.errors.vCPU = 'No change in VM properties.'
    

def get_mail_admin_form():
    form = FORM(TABLE(TR('Type:'),
                TR(TABLE(TR(TD(INPUT(_name='email_type', _type='radio', _value='report_bug', value='report_bug')),TD('Report Bug'),
                TD(INPUT(_name='email_type', _type='radio', _value='request')),TD('Log Request'),
                TD(INPUT(_name='email_type', _type='radio', _value='complaint')),TD('Lodge Complaint')))),TR('Subject:'),
                TR(TEXTAREA(_name='email_subject',_style='height:50px; width:100%', _cols='30', _rows='20',requires=IS_NOT_EMPTY())),TR('Message:'),
                TR(TEXTAREA(_name='email_message',_style='height:100px; width:100%', _cols='30', _rows='20',requires=IS_NOT_EMPTY())),
                
                TR(INPUT(_type = 'submit', _value = 'Send Email')),_style='width:100%; border:0px'))
    return form

def get_vm_history(vm_id):
    
    vm_history = []
    for vm_log in db(db.vm_event_log.vm_id == vm_id).select(orderby = ~db.vm_event_log.timestamp):
        element = {'attribute' : vm_log.attribute,
                   'old_value' : vm_log.old_value,
                   'new_value' : vm_log.new_value,
                   'requested_by' : vm_log.requester_id.first_name + ' ' + vm_log.requester_id.last_name if vm_log.requester_id > 0 else 'System User', 
                   'timestamp' : vm_log.timestamp}
        vm_history.append(element)
    return vm_history


def grant_novnc_access(vm_id):
    
    msg = ""
    active_vnc = db((db.vnc_access.vm_id == vm_id) & (db.vnc_access.status == VNC_ACCESS_STATUS_ACTIVE)).count()
    
    if active_vnc > 0:
        vm_data = db(db.vnc_access.vm_id == vm_id).select().first() 
        token = vm_data.token
        msg = 'VNC access already granted. Please check your mail for further details.'
    else:
        vnc_count = db((db.vnc_access.vm_id == vm_id) & (db.vnc_access.time_requested > (get_datetime() - timedelta(days=1)))).count()
        if vnc_count >= MAX_VNC_ALLOWED_IN_A_DAY :
            msg = 'VNC request has exceeded limit.'
        else:
            try:
                f = os.popen('openssl rand -hex 10')
                token = f.read()
                token = token.split("\n")
                token=token[0]
                create_novnc_mapping(vm_id,token)
                vm_data = db(db.vm_data.id == vm_id).select().first()
                host_ip = vm_data.host_id.host_ip.private_ip
                vnc_port = vm_data.vnc_port
                vnc = str(vnc_port)
                file_token =str(token) +":" + " "  + str(host_ip)+ ":" + str(vnc) + "\n"
                myfile=get_file_append_mode("/home/www-data/token.list")
                myfile.write(file_token)
                command = "ps -ef | grep websockify|awk '{print $2}'"
                port = config.get("NOVNC_CONF","port")
                server_ip = config.get("NOVNC_CONF","server_ip")
                return_value = execute_remote_cmd(server_ip, 'root',command)
                return_value=return_value.split()
                if len(return_value) <=2:                 
                    command = "./noVNC/utils/websockify/run --web /root/noVNC --target-config /home/www-data/token.list " +str(server_ip)+ ":"+str(port) + " > /dev/null 2>&1 &" 
                    return_value = execute_remote_cmd(server_ip, 'root',command)
                msg = 'VNC access granted. Please check your mail for further details.'
            except:
                logger.debug('Some Error Occurred. Please try later')
                log_exception()
                pass

    logger.debug(msg)
    return token

def create_vnc_url(vm_id):
    token = grant_novnc_access(vm_id)
    if token :
        port = config.get("NOVNC_CONF","port")
        url_ip = config.get("NOVNC_CONF","url_ip")     
        vnc_url = "http://" + str(url_ip) +":" + str(port)+"/vnc_auto.html?path=?token=" + str(token) 
    return vnc_url 

def create_novnc_mapping(vm_id,token):
    """
    Create mapping in NAT for VNC access
    """
    vm_data = current.db.vm_data[vm_id]
    duration = 30*60 #30 minutes

    vnc_port = vm_data.vnc_port
    vnc = str(vnc_port)
    vnc = vnc[1:]
    vnc_id = current.db.vnc_access.update_or_insert(vm_id = vm_id,
                                    host_id = vm_data.host_id,
                                    token =token,
                                    vnc_source_port = vnc,
                                    vnc_destination_port = vnc,
                                    duration = duration,
                                    status = VNC_ACCESS_STATUS_INACTIVE)

    try:
        current.db.vnc_access[vnc_id] = dict(status = VNC_ACCESS_STATUS_ACTIVE)
    except:
        log_exception()

def check_vnc(vm_id):
    logger.debug("checking vnc port")
    details=db((db.vnc_access.vm_id == vm_id) & (db.private_ip_pool.id==db.host.host_ip) & (db.vnc_access.host_id==db.host.id)).select(db.private_ip_pool.private_ip,db.vnc_access.vnc_source_port)
    logger.debug(details)
    return details
 
def update_snapshot_flag(vm_id, flag):
    vm_data = db.vm_data[vm_id]
    vm_data.update_record(snapshot_flag=int(flag))
    
def get_my_saved_templates():
    templates = db(db.template.owner.contains(auth.user.id)).select(db.template.ALL)
    for template in templates:
        parent_vm = db.vm_data(saved_template = template.id)
        template['vm_id'] = parent_vm.id if parent_vm else -1
    
    return templates
