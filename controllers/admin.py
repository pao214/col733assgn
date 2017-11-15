# -*- coding: utf-8 -*-
"""
admin.py: This controller has functions that corresponds to the requested actions 
by users with role of system administrator.
"""
###################################################################################
# Added to enable code completion in IDE's.
if 0:
    from gluon import *  # @UnusedWildImport
    from gluon import request, session
    from applications.baadal.models import *  # @UnusedWildImport
###################################################################################
from helper import get_constant, execute_remote_cmd
from host_helper import delete_orphan_vm, HOST_STATUS_MAINTENANCE, HOST_STATUS_UP, \
    HOST_STATUS_DOWN
from log_handler import logger
from maintenance import shutdown_baadal, bootup_baadal
from simplejson import dumps
from vm_utilization import VM_UTIL_10_MINS, check_graph_type, check_graph_period, \
    fetch_info_graph, VM_UTIL_24_HOURS
import json


@check_moderator
@handle_exception
def list_all_vm():
    vm_list = get_all_vm_list()
    return dict(vmlist = vm_list)


def list_all_object_store():
    ob_list = get_all_object_list()
    return dict(oblist = ob_list)

def list_all_containers():
    cont_list = get_all_container_list()
    return dict(contlist = cont_list)

@check_moderator
@handle_exception
def list_all_pending_requests():
    pending_requests = get_all_pending_requests()
    requests = get_segregated_requests(pending_requests)

    return dict(install_requests = requests[0], 
                clone_requests   = requests[1], 
                disk_requests    = requests[2], 
                edit_requests    = requests[3],
                install_object_store_requests = requests[4],
	         	install_container_requests = requests[5])

@check_moderator
@handle_exception
def approve_users():
    pending_users = get_all_unregistered_users()
    users = get_users_with_organisation(pending_users)
    types = get_user_role_types()
    return dict(users = users,
                type_options = types)
 
@check_moderator
@handle_exception
def mail_user():
    vm_id = request.args[0]
    form = get_mail_user_form()
    if form.accepts(request.vars, session):
        email_subject = form.vars.email_subject
        email_message = form.vars.email_message
        send_email_to_user_manual(email_subject, email_message, vm_id)
        redirect(URL(c='default', f='index'))
    return dict(form = form)
              
@check_moderator
@handle_exception
def modify_user_role():
    active_users = get_users_with_roles()
    all_roles = get_user_role_types()
    return dict(users = active_users,
                type_options = all_roles)
    
def modify_roles():
    user_id = request.args[0]
    user_roles = request.args[1]
    if user_roles == "empty":
        user_roles = None
    else:
        user_roles = user_roles.split('_')
    user_id = long(user_id)
    delete_all_user_roles(user_id)
    session.flash= specify_user_roles(user_id, user_roles)
    redirect(URL(c='admin',f='modify_user_role'))

@check_moderator
@handle_exception
def hosts_vms():
    form = get_util_period_form(submit_form=False)
    util_period = VM_UTIL_10_MINS
    form.vars.util_period = util_period
    host_util_data = get_host_util_data(util_period)   
    hostvmlist = get_vm_groupby_hosts()        
    return dict(hostvmlist = hostvmlist, host_util_data = dumps(host_util_data), util_form=form)


@check_moderator
def get_host_utilization_data():
    util_period = request.vars['keywords']
    host_util_data = get_host_util_data(util_period)
    return dumps(host_util_data)

@check_moderator
@handle_exception
def manage_template():
    req_type = request.args(0)
    if req_type == 'delete' or request.vars['delete_this_record'] == 'on':
        can_delete = check_delete_template(request.args(2))
        if not can_delete:
            redirect(URL(c='admin', f='manage_template'))
    form = get_manage_template_form(request.args(0))
    return dict(form = form)

@check_moderator
@handle_exception
def manage_security_domain():

    req_type = request.args(0)
    if req_type == 'delete' or request.vars['delete_this_record'] == 'on':
        error_message = check_delete_security_domain(request.args(2))
        if error_message != None:
            session.flash = error_message
            redirect(URL(c='admin', f='manage_security_domain'))

    form = get_security_domain_form()
    return dict(form = form)

@check_moderator
@handle_exception
def host_details():
    hosts = get_all_hosts()

    form1=get_search_host_form()
    form2=get_configure_host_form()

    if form1.process(formname='form_ip').accepted:
        session.flash='Check the details'
        redirect(URL(c='admin', f='add_host',args=form1.vars.host_ip))
        
    if form2.process(formname='form_mac').accepted:
        message = configure_host_by_mac(form2.vars.host_mac_addr)
        session.flash=message
        redirect(URL(c='admin', f='host_details'))

    return dict(form1=form1, form2=form2, hosts=hosts)   

@check_moderator
@handle_exception
def add_host():
    if_redirect = False
    host_ip = request.args[0]
    form = get_host_form(host_ip)
    if form.accepts(request.vars,session):
        session.flash='New Host added'
        if_redirect = True
    elif form.errors:
        session.flash='Error in form'
    if if_redirect :
        redirect(URL(c='admin', f='host_details'))
    else :
        return dict(form=form)

@check_moderator
@handle_exception
def manage_datastore():
    form = get_manage_datastore_form(request.args(0))
    return dict(form=form)

@check_moderator
@handle_exception
def user_details():
    vm_id = request.args[0]
    form = get_search_user_form()
    if form.accepts(request.vars, session, onvalidation = validate_user):
        redirect(URL(c ='admin', f = 'add_user_to_vm', args = [form.vars.user_id, vm_id]))
    elif form.errors:
        session.form = 'Invalid user id'

    return dict(form=form)

@check_moderator
@handle_exception
def add_container_user():
    cont_id = request.args[0]
    form = get_search_user_form()
    if form.accepts(request.vars, session, onvalidation = validate_user):
        redirect(URL(c ='admin', f = 'add_user_to_container', args = [form.vars.user_id, cont_id]))
    elif form.errors:
        session.form = 'Invalid user id'

    return dict(form=form)

@check_moderator
@handle_exception
def add_user_to_vm():
    username = request.args[0]
    vm_id = request.args[1]
    form = get_user_form(username, vm_id, True)

    if form.accepts(request.vars,session):
        
        user_set = set({form.vars.user_id})
    
        if not is_vm_name_unique(user_set, vm_id=vm_id):
            form.errors.vm_name = 'VM name should be unique for the user.'

        add_user_vm_access(vm_id, form.vars.user_id)
        session.flash = "User is added to vm"
        redirect(URL(r = request, c = 'user', f = 'settings', args = vm_id))
    elif form.errors:
        session.form = 'Error in form'
    return dict(form = form)

@check_moderator
@handle_exception
def add_user_to_container():
    username = request.args[0]
    cont_id = request.args[1]
    form = get_user_form(username, cont_id, False)

    if form.accepts(request.vars,session):
        
        add_user_cont_access(cont_id, form.vars.user_id)
        session.flash = "User is added to Container"
        redirect(URL(r = request, c = 'user', f = 'cont_settings', args = cont_id))
    elif form.errors:
        session.form = 'Error in form'
    return dict(form = form)


@check_moderator
@handle_exception
def delete_user_vm():
    vm_id=request.args[0]
    user_id=request.args[1]
    delete_user_vm_access(int(vm_id), int(user_id))    			
    session.flash = 'User access for the VM is removed.'
    redirect(URL(r = request, c = 'user', f = 'settings', args = vm_id))

@check_moderator
@handle_exception
def delete_user_cont():
    cont_id=request.args[0]
    user_id=request.args[1]
    delete_user_cont_access(int(cont_id), int(user_id))                
    session.flash = 'User access for the Container is removed.'
    redirect(URL(r = request, c = 'user', f = 'cont_settings', args = cont_id))

@check_moderator
@handle_exception
def migrate_vm():

    vm_id = request.args[0]
    vm_details = get_migrate_vm_details(vm_id)
    if len(request.args) > 1:
        params={}
        if request.args[1] == 'migrate_vm_hosts':

            params['destination_host'] = request.vars['selected_host']
            params['live_migration'] = request.vars['live_migration']
            add_vm_task_to_queue(vm_id, VM_TASK_MIGRATE_HOST, params)

        elif request.args[1] == 'migrate_vm_datastores':

            params['destination_ds'] = request.vars['selected_datastore']
            params['live_migration'] = request.vars['live_migration']
            add_vm_task_to_queue(vm_id, VM_TASK_MIGRATE_DS, params)

        session.flash = 'Your task has been queued. Please check your task list for status.'
        redirect(URL(c = 'admin', f = 'hosts_vms'))
    logger.debug("vm_details[affinity flag] :  " + str(vm_details['affinity_flag']))
    if vm_details['affinity_flag'] != 0:
        host_details = get_host_details(vm_details['vm_name'])
        logger.debug("available_hosts : " + str(host_details['available_hosts']))
        vm_details['available_hosts'] = host_details['available_hosts']
    return dict(vm_details=vm_details)


@check_moderator
@handle_exception
def affinity_host():
    vm_id = request.args[0]
    vm_details = get_vm_host_details(vm_id)

    params={} 
    host_details=[]
    if len(request.args) > 1:
        if request.args[1] == 'affinity_host':
            host_details = get_host_details(vm_id)
        params['affinity_host'] = request.vars['test']
        host_data = add_data_into_affinity(params, vm_id)  
        if host_data == None:
            session.flash = 'Please select host for set Affinity'
            redirect(URL(r = request, c = 'admin', f = 'affinity_host',args = vm_id)) 
        host_details = get_host_details(vm_id) 
    return dict(vm_details=vm_details, host_details=host_details)
    

@check_moderator
@handle_exception
def delete_affinity_vm():
    vm_id = request.args[0]
    key = request.args[1]
    reset_host_affinity(vm_id,key)
    session.flash = 'host affinity removed.'
    redirect(URL(r = request, c = 'admin', f = 'affinity_host',args = vm_id))
      
   
@check_moderator
@handle_exception
def lockvm():
    vm_id=request.args[0]
    vminfo=get_vm_info(vm_id)
    if(not vminfo.locked):
        add_vm_task_to_queue(vm_id, VM_TASK_DESTROY)
        session.flash = "VM will be force Shutoff and locked. Check the task queue."
        update_vm_lock(vm_id,True)
    else:
        update_vm_lock(vm_id,False)
        session.flash = "Lock Released. Start VM yourself."
    redirect(URL(r = request, c = 'user', f = 'settings', args = vm_id))

@check_moderator
@handle_exception
def task_list():

    form = get_task_num_form()
    task_num = ITEMS_PER_PAGE
    form.vars.task_num = task_num

    if form.accepts(request.vars, session, keepvalues=True):
        task_num = int(form.vars.task_num)
    
    pending = get_task_by_status([TASK_QUEUE_STATUS_PENDING], task_num)
    success = get_task_by_status([TASK_QUEUE_STATUS_SUCCESS], task_num)
    failed = get_task_by_status([TASK_QUEUE_STATUS_FAILED, TASK_QUEUE_STATUS_PARTIAL_SUCCESS], task_num)
    
    return dict(pending=pending, success=success, failed=failed, form=form)

@check_moderator
@handle_exception
def ignore_task():
    task_id=request.args[0]
    update_task_ignore(task_id)
    
    redirect(URL(r=request,c='admin',f='task_list'))

@check_moderator
@handle_exception
def retry_task():
    event_id=request.args[0]
    update_task_retry(event_id)
    
    redirect(URL(r=request,c='admin',f='task_list'))

@check_moderator
@handle_exception
def delete_machine():   
    vm_id=request.args[0]
    add_vm_task_to_queue(vm_id, VM_TASK_DELETE)    

    redirect(URL(r = request, c = 'user', f = 'settings', args = vm_id))

@check_moderator
def sanity_check():

    form = get_host_sanity_form()
    host_selected = -1
    form.vars.host_selected = host_selected

    if form.accepts(request.vars, session, keepvalues=True):
        host_selected = int(form.vars.host_selected)
    
    output = check_vm_sanity(host_selected) if host_selected != -1 else []
    
    return dict(sanity_data=output, form=form)
    
@check_moderator
def cont_sanity_check():

    output = check_cont_sanity()
    
    return dict(sanity_data=output)
    
@check_moderator
def sync_container():
    task = request.args[0]
    cont_info = request.args[1]
    if task == 'Delete_Orphan':
        delete_orphan_cont(cont_info)
    elif task == 'Add_Orphan_Cont':
        add_orphan_cont(cont_info)
    elif task == 'Delete_Cont_Info':
        delete_cont_info(cont_info)
    redirect(URL(r=request,c='admin',f='cont_sanity_check'))
    
@check_moderator
def sync_vm():
    task = request.args[0]
    vm_name = request.args[1]
    host_id = request.args[2]
    if task == 'Delete_Orphan':
        delete_orphan_vm(vm_name, host_id)
    elif task == 'Add_Orphan':
        add_orphan_vm(vm_name, host_id)
    elif task == 'Delete_VM_Info':
        delete_vm_info(vm_name)
    redirect(URL(r=request,c='admin',f='sanity_check'))
    
@check_moderator
def snapshot_sanity_check():
    vm_id = request.args[0]
    output = check_vm_snapshot_sanity(vm_id)
    return dict(vm_id=output[0], vm_name=output[1], snapshots=output[2])

@check_moderator
def sync_snapshot():
    task = request.vars['action_type']
    vm_id = request.vars['vm_id']
    logger.debug(request.args)
    if task == 'Delete_Orphan':
        vm_name = request.vars['vm_name']
        snapshot_name = request.vars['snapshot_name']
        delete_orphan_snapshot(vm_name, snapshot_name)
    elif task == 'Delete_Snapshot_Info':
        snapshot_id = request.vars['snapshot_id']
        delete_snapshot_info(snapshot_id)
    redirect(URL(r=request,c='admin',f='snapshot_sanity_check', args = vm_id))
    
@check_moderator
@handle_exception
def approve_request():
    request_id=request.args[0] 
    enqueue_vm_request(request_id);
    session.flash = 'Installation request added to queue'
    redirect(URL(c='admin', f='list_all_pending_requests'))

@check_moderator
@handle_exception
def reject_request():
    request_id=request.args[0]
    reject_vm_request(request_id);
    session.flash = 'Request Rejected'
    redirect(URL(c='admin', f='list_all_pending_requests'))

@check_moderator
@handle_exception
def maintenance_host():
    logger.debug("INSIDE MAINTENANCE HOST FUNCTION")
    host_id=request.args[0]
    #migration requests to be added to queue
    update_host_status(host_id, HOST_STATUS_MAINTENANCE)
    redirect(URL(c='admin', f='host_details'))
    
@check_moderator
@handle_exception
def boot_up_host():
    logger.debug("INSIDE BOOT UP HOST FUNCTION")
    host_id=request.args[0]
    if not (update_host_status(host_id, HOST_STATUS_UP)):
        session.flash = 'Host not accessible. Please verify'
    redirect(URL(c='admin', f='host_details'))
    
@check_moderator
@handle_exception
def shut_down_host():
    logger.debug("INSIDE SHUTDOWN HOST FUNCTION")
    host_id=request.args[0]
    #shut down to be implemented
    update_host_status(host_id, HOST_STATUS_DOWN)
    redirect(URL(c='admin', f='host_details'))
    
@check_moderator
@handle_exception
def delete_host():
    host_id=request.args[0]
    delete_host_from_db(host_id)
    redirect(URL(c='admin', f='host_details'))
    
@check_moderator
@handle_exception
def manage_public_ip_pool():
    req_type = request.args(0)
    if req_type == 'delete' or request.vars['delete_this_record'] == 'on':
        error_message = is_ip_assigned(request.args(2), is_private=False)
        if error_message != None:
            session.flash = error_message
            redirect(URL(c='admin', f='manage_public_ip_pool'))
        else:
            session.flash = 'Public IP deleted successfully'
    form = get_manage_public_ip_pool_form()
    return dict(form=form)

@check_moderator
@handle_exception
def validate_public_ip_range():
    rangeFrom = request.vars['rangeFrom']
    rangeTo = request.vars['rangeTo']
    
    from helper import validate_ip_range
    if validate_ip_range(rangeFrom, rangeTo):
        failed = add_public_ip_range(rangeFrom, rangeTo)
        return str(failed)
    else:
        return '-1'

@check_moderator
@handle_exception
def validate_private_ip_range():
    rangeFrom = request.vars['rangeFrom']
    rangeTo = request.vars['rangeTo']
    vlan = request.vars['vlan']
    
    from helper import validate_ip_range
    if validate_ip_range(rangeFrom, rangeTo):
        failed = add_private_ip_range(rangeFrom, rangeTo, int(vlan))
        return str(failed)
    else:
        return '-1'

@check_moderator
@handle_exception
def manage_private_ip_pool():
    
    req_type = request.args(0)
    if req_type == 'delete' or request.vars['delete_this_record'] == 'on':
        error_message = is_ip_assigned(request.args(2), is_private=True)
        if error_message != None:
            session.flash = error_message
            redirect(URL(c='admin', f='manage_private_ip_pool'))
        else:
            session.flash = 'Private IP deleted successfully'
            
    form = get_manage_private_ip_pool_form()
    return dict(form=form)

@check_moderator
@handle_exception
def vm_utilization():

    form = get_util_period_form()
    util_period = VM_UTIL_24_HOURS
    form.vars.util_period = util_period

    if form.accepts(request.vars, session, keepvalues=True):
        util_period = int(form.vars.util_period)
    
    vm_util_data = get_vm_util_data(util_period)
    
    return dict(vm_util_data=vm_util_data, form=form)

@check_moderator
@handle_exception
def remind_orgadmin():
    vm_id=request.args[0]
    send_remind_orgadmin_email(vm_id)
    session.flash = 'Organisation Admin Reminded'
    redirect(URL(c='orgadmin', f='pending_approvals'))

@check_moderator
@handle_exception
def verify_vm_resource():

    request_id = request.vars['request_id']
    return check_vm_resource(request_id)

@check_moderator
@handle_exception
def add_user_with_role():
    user_id = request.args[0]
    user_roles = request.args[1]
    if user_roles == "empty":
        user_roles = None
    else:
        user_roles = user_roles.split('_')
    user_id = long(user_id)
    send_email_on_successful_registration(user_id)
    session.flash= specify_user_roles(user_id, user_roles)
    redirect(URL(c='admin',f='approve_users'))
 
@check_moderator
@handle_exception   
def remove_user():
    user_id=request.args[0]
    send_email_on_registration_denied(user_id)
    session.flash = disable_user(user_id)
    redirect(URL(c='admin',f='approve_users'))

@check_moderator
@handle_exception   
def baadal_status():
    vm_list = get_baadal_status_info()
    baadal_status = get_constant('baadal_status')
    return dict(vm_list=vm_list, baadal_status=baadal_status)

@check_moderator
@handle_exception   
def start_shutdown():
    shutdown_baadal()

@check_moderator
@handle_exception   
def send_shutdown_mail():
    send_shutdown_email_to_all()
    
@check_moderator
@handle_exception   
def start_bootup():
    bootup_baadal()


@check_moderator
@handle_exception             
def show_cont_performance():
    ip_cmd="/sbin/ifconfig | grep 'inet addr' | sed -n '1p' | awk '{print $2}' | cut -d ':' -f 2"
    cpu_cmd="nproc"
    mem_cmd = "free -m | grep 'Mem:' | awk '{print $2}'"
    cont_cpu=execute_remote_cmd("localhost", 'root', cpu_cmd, None,  True).strip()
    cont_ram=execute_remote_cmd("localhost", 'root', mem_cmd, None,  True).strip()
    cont_ip=execute_remote_cmd("localhost", 'root', ip_cmd, None,  True).replace(".","_").strip()
    return dict(host_identity=cont_ip ,host_ram=cont_ram, m_type="host",host_cpu=cont_cpu)

@check_moderator
@handle_exception 
def show_nat_performance():
    ip_cmd="/sbin/route -n | sed -n '3p' | awk '{print $2}'"
    cpu_cmd="nproc"
    mem_cmd = "free -m | grep 'Mem:' | awk '{print $2}'"
    nat_ip=execute_remote_cmd("localhost", 'root', ip_cmd, None,  True).strip()
    nat_cpu=execute_remote_cmd(nat_ip, 'root', cpu_cmd, None,  True)[0].strip()
    nat_ram=execute_remote_cmd(nat_ip, 'root', mem_cmd, None,  True)[0].strip()
    nat_identity=nat_ip.replace(".","_")
    return dict(host_identity= nat_identity ,host_ram=nat_ram, m_type="host",host_cpu=nat_cpu)

@check_moderator
@handle_exception       
def show_host_performance():

    host_id = request.args(0)
    host_info = get_host_config(host_id)
    host_identity = str(host_info.host_ip.private_ip).replace('.','_')
    host_cpu=host_info.CPUs

    host_ram=host_info.RAM
    logger.debug(host_cpu)
    logger.debug(type(host_cpu))
    m_type="host"
    return dict(host_id=host_id, host_identity=host_identity ,host_ram=host_ram, m_type=m_type,host_cpu=host_cpu)


def create_graph_for_host():
    ret={}

    graph_period=request.vars['graphPeriod']
    vm_ram=request.vars['host_RAM']
    vm_identity=request.vars['hostIdentity']
    g_type=request.vars['graphType']
    m_type=request.vars['mtype']
    host_cpu=request.vars['host_CPU']
    title=check_graph_type(g_type, vm_ram, m_type)
    logger.debug("Checking machine type :" + str(m_type))
    ret['valueformat']=check_graph_period(graph_period)
    ret['y_title']=title['y_title']
    ret['g_title']=title['g_title']
    
    ret['data']=fetch_info_graph(vm_identity,graph_period,g_type,vm_ram,m_type,host_cpu)
    logger.debug(ret['data'])
    ret['mem']=float(vm_ram)/(1024) if int(vm_ram)>1024 else vm_ram
    

    if g_type=='disk':
        ret['legend_read']='disk read'
        ret['legend_write']='disk write'
        ret['limit']=400000000
    elif g_type=='nw':
        ret['legend_read']='network read'
        ret['legend_write']='network write'
        ret['limit']=3,00,000
    elif g_type=='cpu':
        ret['name']='cpu'
        ret['limit']=100
    elif g_type=='tmp':
        ret['name']='tmp'
        ret['limit']=60
    elif g_type=='power':
        ret['name']='power'
        ret['limit']=400
    else:
        ret['name']='mem'
        ret['limit']=ret['mem']	
    
    json_str = json.dumps(ret, ensure_ascii=False)
    
    return json_str

        
@check_moderator
@handle_exception       
def host_config():
    host_id=request.args(0)
    host_info = get_host_config(host_id)
    logger.debug(host_info)
    return dict(host_info=host_info)


def show_mc_performance(info):
    return dict()

@check_moderator
@handle_exception       
def verify_user():
    username = request.vars['keywords']
    user_info = get_user_info(username)
    if user_info != None:
        return user_info[1]


@check_moderator
@handle_exception       
def launch_vm_image():
    form = get_launch_vm_image_form()
    
    if form.accepts(request.vars, session, onvalidation=launch_vm_image_validation):
        
        exec_launch_vm_image(form.vars.id, form.vars.collaborators, form.vars.extra_disk_list)
        
        logger.debug('VM image launched successfully')
        redirect(URL(c='default', f='index'))
    return dict(form=form)

@check_moderator
@handle_exception       
def get_private_ip_list():
    security_domain_id = request.vars['keywords']
    return get_private_ip_xml(security_domain_id)


@check_moderator
@handle_exception       
def get_public_ip_list():
    return get_public_ip_xml()

@check_moderator
@handle_exception       
def verify_extra_disk():
    vm_image_name = request.vars['vm_image_name']
    disk_name = request.vars['disk_name']
    datastore_id = request.vars['datastore_id']

    disk_info = check_vm_extra_disk(vm_image_name, disk_name, datastore_id)
    return disk_info

def network_graph():
    return dict()


def host_network_graph():
    return dict()


############### host tree ##################
def create_zoom_tree():
    g_type=request.vars['graphType']
    ret=zoom_info(g_type)
    json_str = json.dumps(ret, ensure_ascii=False)
    return json_str


def zoom_tree():
    return dict()

@check_moderator
@handle_exception
def nodes_containers():
    return dict(output=get_node_container_list())
