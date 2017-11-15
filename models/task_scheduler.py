# -*- coding: utf-8 -*-
###################################################################################
# Added to enable code completion in IDE's.
if 0:
    from gluon import db,request, cache
    from applications.baadal.models import *  # @UnusedWildImport
###################################################################################
from helper import get_datetime, log_exception, is_pingable, execute_remote_cmd
from vm_helper import create_object_store,install, start, suspend, resume, destroy, delete, migrate, snapshot,\
    revert, delete_snapshot, edit_vm_config, clone, attach_extra_disk, migrate_datastore,\
    save_vm_as_template, delete_template
from host_helper import host_status_sanity_check, collect_data_from_host
from vm_utilization import update_rrd
from nat_mapper import clear_all_timedout_vnc_mappings
from log_handler import logger, rrd_logger
from host_helper import HOST_STATUS_UP
from load_balancer import find_host_and_guest_list, loadbalance_vm
#from container_create import install_cont, start_cont, stop_cont, suspend_cont,\
#    resume_cont, delete_cont, restart_cont, recreate_cont, backup_cont
from gluon import current
current.cache = cache

import os

task = {
	
	    VM_TASK_CREATE              :    install,
        VM_TASK_START               :    start,
        VM_TASK_STOP                :    destroy,
        VM_TASK_SUSPEND             :    suspend,
        VM_TASK_RESUME              :    resume,
        VM_TASK_DESTROY             :    destroy,
        VM_TASK_DELETE              :    delete,
        VM_TASK_MIGRATE_HOST        :    migrate,
        VM_TASK_MIGRATE_DS          :    migrate_datastore,
        VM_TASK_SNAPSHOT            :    snapshot,
        VM_TASK_REVERT_TO_SNAPSHOT  :    revert,
        VM_TASK_DELETE_SNAPSHOT     :    delete_snapshot,
        VM_TASK_EDIT_CONFIG         :    edit_vm_config,
        VM_TASK_CLONE               :    clone,
        VM_TASK_ATTACH_DISK         :    attach_extra_disk,
        VM_TASK_SAVE_AS_TEMPLATE    :    save_vm_as_template,
        VM_TASK_DELETE_TEMPLATE     :    delete_template
#        CONTAINER_TASK_CREATE       :    install_cont,
#        CONTAINER_START             :    start_cont,
#        CONTAINER_STOP              :    stop_cont,
#        CONTAINER_SUSPEND           :    suspend_cont,
#        CONTAINER_RESUME            :    resume_cont,
#        CONTAINER_DELETE            :    delete_cont,
#        CONTAINER_RESTART           :    restart_cont,
#        CONTAINER_RECREATE          :    recreate_cont,
#        CONTAINER_COMMIT            :    backup_cont
       }


def _send_vm_task_complete_mail(task_event):
    
    vm_users = []
    vm_id = task_event.parameters['vm_id'] if 'vm_id' in task_event.parameters else None
    if vm_id:
        for user in db(db.user_vm_map.vm_id == vm_id).select(db.user_vm_map.user_id):
            vm_users.append(user['user_id'])
    else:
        vm_users.append(task_event.requester_id)
    send_email_to_user(task_event.task_type, task_event.vm_name, task_event.start_time, vm_users)


def _send_cont_task_complete_mail(task_event):
    
    cont_users = []
    cont_id = task_event.parameters['cont_id'] if 'cont_id' in task_event.parameters else None
    if cont_id:
        for user in db(db.user_container_map.cont_id == cont_id).select(db.user_container_map.user_id):
            cont_users.append(user['user_id'])
    else:
        cont_users.append(task_event.requester_id)
    send_email_to_user(task_event.task_type, task_event.vm_name, task_event.start_time, cont_users)

def _send_object_task_complete_mail(task_event, object_name):

    vm_users = []
    vm_id = task_event.parameters['vm_id'] if 'vm_id' in task_event.parameters else None
    if vm_id:
        for user in db(db.user_object_map.ob_id == vm_id).select(db.user_vm_map.user_id):
            vm_users.append(user['user_id'])
    else:
        vm_users.append(task_event.requester_id)
    send_email_to_user(task_event.task_type, object_name, task_event.start_time, vm_users)

    
def _log_vm_event(old_vm_data, task_queue_data):
    """
    Logs action data into vm_event_log table
    """
    vm_data = db.vm_data[old_vm_data.id]
    if task_queue_data.task_type in (VM_TASK_START, 
                                     VM_TASK_STOP, 
                                     VM_TASK_SUSPEND, 
                                     VM_TASK_RESUME, 
                                     VM_TASK_DESTROY):
        db.vm_event_log.insert(vm_id = vm_data.id,
                               attribute = 'VM Status',
                               requester_id = task_queue_data.requester_id,
                               old_value = get_vm_status(old_vm_data.status),
                               new_value = get_vm_status(vm_data.status))
    elif task_queue_data.task_type == VM_TASK_EDIT_CONFIG:
        parameters = task_queue_data.parameters
        data_list = []
        if 'vcpus' in parameters:
            vm_log = {'vm_id' : vm_data.id, 
                      'requester_id' : task_queue_data.requester_id,
                      'attribute' : 'Edit CPU',
                      'old_value' : str(old_vm_data.vCPU) + ' CPU',
                      'new_value' : str(vm_data.vCPU) + ' CPU'}
            data_list.append(vm_log)
        if 'ram' in parameters:
            vm_log = {'vm_id' : vm_data.id, 
                      'requester_id' : task_queue_data.requester_id,
                      'attribute' : 'Edit RAM',
                      'old_value' : str(old_vm_data.RAM) + ' MB',
                      'new_value' : str(vm_data.RAM) + ' MB'}
            data_list.append(vm_log)
        if 'public_ip' in parameters:
            vm_log = {'vm_id' : vm_data.id, 
                      'requester_id' : task_queue_data.requester_id,
                      'attribute' : 'Public IP',
                      'old_value' : old_vm_data.public_ip,
                      'new_value' : vm_data.public_ip}
            data_list.append(vm_log)
        if 'security_domain' in parameters:
            vm_log = {'vm_id' : vm_data.id, 
                      'requester_id' : task_queue_data.requester_id,
                      'attribute' : 'Security Domain',
                      'old_value' : old_vm_data.security_domain.name,
                      'new_value' : vm_data.security_domain.name}
            data_list.append(vm_log)
            vm_log = {'vm_id' : vm_data.id, 
                      'requester_id' : task_queue_data.requester_id,
                      'attribute' : 'Private IP',
                      'old_value' : old_vm_data.private_ip,
                      'new_value' : vm_data.private_ip}
            data_list.append(vm_log)
        db.vm_event_log.bulk_insert(data_list)
    elif task_queue_data.task_type == VM_TASK_ATTACH_DISK:
        db.vm_event_log.insert(vm_id = vm_data.id,
                               attribute = 'Attach Disk',
                               requester_id = task_queue_data.requester_id,
                               old_value = str(old_vm_data.extra_HDD)+' GB',
                               new_value = str(vm_data.extra_HDD)+' GB')


def process_object_task(task_event_id):
    """Invoked when scheduler runs task of type 'object_task'
    For every task, function calls the corresponding handler
    and updates the database on the basis of the response """

    logger.info("\n ENTERING OBJECT_TASK	........")
    task_event_data = db.task_queue_event[task_event_id]
    task_queue_data = db.task_queue[task_event_data.task_id]
    object_data = db.object_store_data[task_event_data.parameters['vm_id']] if task_event_data.parameters['vm_id'] != None else None
    try:
        #Update attention_time for task in the event table
        task_event_data.update_record(attention_time=get_datetime(), status=TASK_QUEUE_STATUS_PROCESSING)
        #Call the corresponding function from vm_helper
        logger.debug("Starting OBJECT_TASK processing...")
        ret = create_object_store(task_event_id,object_data)
        logger.debug("Completed OBJECT_TASK processing...")
        #On return, update the status and end time in task event table
        task_event_data.update_record(status=ret[0], message=ret[1], end_time=get_datetime())

        if ret[0] == TASK_QUEUE_STATUS_FAILED:
            logger.debug("OBJECT_TASK FAILED")
            logger.debug("OBJECT_TASK Error Message: %s" % ret[1])
            task_queue_data.update_record(status=TASK_QUEUE_STATUS_FAILED)

        elif ret[0] == TASK_QUEUE_STATUS_SUCCESS:
            # Create log event for the task
            logger.debug("OBJECT_TASK SUCCESSFUL")
            if object_data:
                logger.info("\n object_data: %s" %object_data)
            # For successful task, delete the task from queue 
            if db.task_queue[task_queue_data.id]:
                del db.task_queue[task_queue_data.id]
            if 'request_id' in task_queue_data.parameters:
                del db.request_queue[task_queue_data.parameters['request_id']]

            _send_object_task_complete_mail(task_event_data, object_data['object_store_name'])
    except:
        msg = log_exception()
        task_event_data.update_record(status=TASK_QUEUE_STATUS_FAILED, message=msg)

    finally:
        db.commit()
        logger.info("EXITING OBJECT_TASK........\n")


def process_vm_task_queue(task_event_id):
    """
    Invoked when scheduler runs task of type 'vm_task'
    For every task, function calls the corresponding handler
    and updates the database on the basis of the response 
    """
    logger.info("\n ENTERING VM_TASK........")
    
    task_event_data = db.task_queue_event[task_event_id]
    task_queue_data = db.task_queue[task_event_data.task_id]
    vm_data = db.vm_data[task_event_data.vm_id] if task_event_data.vm_id != None else None
    try:
        #Update attention_time for task in the event table
        task_event_data.update_record(attention_time=get_datetime(), status=TASK_QUEUE_STATUS_PROCESSING)
        #Call the corresponding function from vm_helper
        logger.debug("Starting VM_TASK processing...")
        ret = task[task_queue_data.task_type](task_queue_data.parameters)
        logger.debug("Completed VM_TASK processing...")

        #On return, update the status and end time in task event table
        task_event_data.update_record(status=ret[0], message=ret[1], end_time=get_datetime())
        
        if ret[0] == TASK_QUEUE_STATUS_FAILED:

            logger.debug("VM_TASK FAILED")
            logger.debug("VM_TASK Error Message: %s" % ret[1])
            task_queue_data.update_record(status=TASK_QUEUE_STATUS_FAILED)

        elif ret[0] == TASK_QUEUE_STATUS_SUCCESS:
            # Create log event for the task
            logger.debug("VM_TASK SUCCESSFUL")
            if vm_data:
                _log_vm_event(vm_data, task_queue_data)
            # For successful task, delete the task from queue 
            if db.task_queue[task_queue_data.id]:
                del db.task_queue[task_queue_data.id]
            if 'request_id' in task_queue_data.parameters:
                del db.request_queue[task_queue_data.parameters['request_id']]
            
            if task_event_data.task_type not in (VM_TASK_MIGRATE_HOST, VM_TASK_MIGRATE_DS):
                _send_vm_task_complete_mail(task_event_data)
        
    except:
        msg = log_exception()
        task_event_data.update_record(status=TASK_QUEUE_STATUS_FAILED, message=msg)
        
    finally:
        db.commit()
        logger.info("EXITING VM_TASK........\n")


def process_container_queue(task_event_id):
    """
    Invoked when scheduler runs task of type 'Container_Task'
    For every task, function calls the corresponding handler
    and updates the database on the basis of the response 
    """
    logger.info("\n ENTERING Container_Task........")
    
    task_event_data = db.task_queue_event[task_event_id]
    task_queue_data = db.task_queue[task_event_data.task_id]
    container_data = db.container_data[task_event_data.cont_id] if task_event_data.cont_id != None else None
    try:
        #Update attention_time for task in the event table
        task_event_data.update_record(attention_time=get_datetime(), status=TASK_QUEUE_STATUS_PROCESSING)
        #Call the corresponding function from vm_helper
        logger.debug("Starting Container_Task processing...")
        ret = task[task_queue_data.task_type](task_queue_data.parameters)
        logger.debug("Completed Container_Task processing...")

        #On return, update the status and end time in task event table
        task_event_data.update_record(status=ret[0], message=ret[1], end_time=get_datetime())
        
        if ret[0] == TASK_QUEUE_STATUS_FAILED:

            logger.debug("Container_Task FAILED")
            logger.debug("Container_Task Error Message: %s" % ret[1])
            task_queue_data.update_record(status=TASK_QUEUE_STATUS_FAILED)

        elif ret[0] == TASK_QUEUE_STATUS_SUCCESS:
            # Create log event for the task
            logger.debug("Container_Task SUCCESSFUL")
            if container_data:
                _log_vm_event(container_data, task_queue_data)
            # For successful task, delete the task from queue 
            if db.task_queue[task_queue_data.id]:
                del db.task_queue[task_queue_data.id]
            if 'request_id' in task_queue_data.parameters:
                del db.request_queue[task_queue_data.parameters['request_id']]
            
            if task_event_data.task_type not in (VM_TASK_MIGRATE_HOST, VM_TASK_MIGRATE_DS):
                _send_cont_task_complete_mail(task_event_data)
        
    except:
        msg = log_exception()
        task_event_data.update_record(status=TASK_QUEUE_STATUS_FAILED, message=msg)
        
    finally:
        db.commit()
        logger.info("EXITING Container_Task........\n")



def process_clone_task(task_event_id, vm_id):
    """
    Invoked when scheduler runs task of type 'clone_task'
    When multiple clones of a VM is requested, multiple tasks are created in scheduler,
    so that they can run concurrently. 
    This function ensures that the status of clone request is updated on the basis of all 
    corresponding asynchronous tasks 
    """
    vm_data = db.vm_data[vm_id]
    logger.debug("ENTERING CLONE_TASK.......")
    logger.debug("Task Id: %s" % task_event_id)
    logger.debug("VM to be Cloned: %s" % vm_data.vm_name)
    task_event = db.task_queue_event[task_event_id]
    task_queue = db.task_queue[task_event.task_id]
    message = task_event.message if task_event.message != None else ''
    try:
        # Update attention time for first clone task
        if task_event.attention_time == None:
            task_event.update_record(attention_time=get_datetime())
        logger.debug("Starting VM Cloning...")
        ret = task[VM_TASK_CLONE](vm_id)
        logger.debug("Completed VM Cloning...")

        if ret[0] == TASK_QUEUE_STATUS_FAILED:
            logger.debug("VM Cloning Failed")
            logger.debug("Failure Message: %s" % ret[1])
            message = message + '\n' + vm_data.vm_name + ': ' + ret[1]
            vm_data.update_record(status = VM_STATUS_UNKNOWN)
        elif ret[0] == TASK_QUEUE_STATUS_SUCCESS:
            logger.debug("VM Cloning Successful")
            params = task_queue.parameters
            # Delete successful vms from list. So, that in case of retry, only failed requests are retried.
            params['clone_vm_id'].remove(vm_id)
            task_queue.update_record(parameters=params)
        
        clone_vm_list = task_event.parameters['clone_vm_id']
        # Remove VM id from the list. This is to check if all the clones for the task are processed.
        clone_vm_list.remove(vm_id)
        
        # Find the status of all clone tasks combined
        current_status = ret[0]
        if task_event.status != TASK_QUEUE_STATUS_PENDING and task_event.status != current_status:
            current_status = TASK_QUEUE_STATUS_PARTIAL_SUCCESS
        
        if not clone_vm_list: #All Clones are processed
            if current_status == TASK_QUEUE_STATUS_SUCCESS:
                del db.request_queue[task_queue.parameters['request_id']]
                del db.task_queue[task_queue.id]
            else:
                if 'request_id' in task_queue.parameters:
                    db.request_queue[task_queue.parameters['request_id']] = dict(status = REQ_STATUS_FAILED)
                task_queue.update_record(status=current_status)
            task_event.update_record(status=current_status, message=message, end_time=get_datetime())
        else:
            task_event.update_record(parameters={'clone_vm_id' : clone_vm_list}, status=current_status, message=message)

    except:
        msg = log_exception()
        vm_data = db.vm_data[vm_id]
        message = message + '\n' + vm_data.vm_name + ': ' + msg
        task_event.update_record(status=TASK_QUEUE_STATUS_FAILED, message=message)

    finally:
        db.commit()
        logger.debug("EXITING CLONE_TASK........")

def process_snapshot_vm(snapshot_type, vm_id = None, frequency=None):
    """
    Handles snapshot task
    Invoked when scheduler runs task of type 'snapshot_vm'
    """
    logger.debug("ENTERING SNAPSHOT VM TASK........Snapshot Type: %s"% snapshot_type)
    try:
        if snapshot_type == SNAPSHOT_SYSTEM:
            params={'snapshot_type' : frequency, 'vm_id' : vm_id}
            task[VM_TASK_SNAPSHOT](params)

        else:    
            vms = db(db.vm_data.status.belongs(VM_STATUS_RUNNING, VM_STATUS_SUSPENDED, VM_STATUS_SHUTDOWN)).select()
            for vm_data in vms:
                flag = vm_data.snapshot_flag

                if(snapshot_type & flag):
                    logger.debug("snapshot_type" + str(snapshot_type))
                    vm_scheduler.queue_task(TASK_SNAPSHOT, 
                                            group_name = 'snapshot_task', 
                                            pvars = {'snapshot_type' : SNAPSHOT_SYSTEM, 'vm_id' : vm_data.id, 'frequency' : snapshot_type}, 
                                            start_time = request.now, 
                                            timeout = 60 * MINUTES)
    except:
        log_exception()
        pass
    finally:
        db.commit()
        logger.debug("EXITING SNAPSHOT VM TASK........")
          
def vm_sanity_check():
    """
    Handles periodic VM sanity check
    Invoked when scheduler runs task of type 'vm_sanity'
    """
    logger.info("ENTERNING VM SANITY CHECK........")
    try:
        check_vm_sanity()
    except:
        log_exception()
        pass
    finally:
        logger.debug("EXITING VM SANITY CHECK........")

def host_sanity_check():
    """
    Handles periodic Host sanity check
    Invoked when scheduler runs task of type 'host_sanity'
    """
    logger.info("ENTERNING HOST SANITY CHECK........")
    try:
        host_status_sanity_check()
    except:
        log_exception()
        pass
    finally:
        logger.debug("EXITING HOST SANITY CHECK........")

def check_vnc_access():
    """
    Clears all timed out VNC Mappings
    Invoked when scheduler runs task of type 'vnc_access'
    """
    logger.info("ENTERNING CLEAR ALL TIMEDOUT VNC MAPPINGS")
    try:
        clear_all_timedout_vnc_mappings()
    except:
        log_exception()
        pass
    finally: 
        logger.debug("EXITING CLEAR ALL TIMEDOUT VNC MAPPINGS........")

########################RRD################################################3

def vm_utilization_rrd(host_ip,m_type=None):
    """
    Handles periodic collection of VM and Host utilization data and updates of 
    respective RRD file.
    """
    logger.info("ENTERING RRD UPDATION/CREATION........on host: %s" % host_ip)
    try:
        
        rrd_logger.debug("Starting RRD Processing for Host: %s" % host_ip)
        rrd_logger.debug(host_ip)
        
        if is_pingable(host_ip):
            update_rrd(host_ip,m_type)
 
        else:
            rrd_logger.error("UNABLE TO UPDATE RRDs for host : %s" % host_ip)

    except Exception as e:

        rrd_logger.debug("ERROR OCCURED: %s" % e)
 
    finally:
        rrd_logger.debug("Completing RRD Processing for Host: %s" % host_ip)
        logger.debug("EXITING RRD UPDATION/CREATION........on host: %s" % host_ip)

#Updating NAT/Controller rrd file
def task_rrd():
    list_host=[]
    cont_ip_cmd="/sbin/ifconfig | grep 'inet addr' | sed -n '1p' | awk '{print $2}' | cut -d ':' -f 2"
    nat_ip_cmd="/sbin/route -n | sed -n '3p' | awk '{print $2}'"
    cont_ip=execute_remote_cmd("localhost", 'root',cont_ip_cmd, None,  True).strip()
    nat_ip=execute_remote_cmd("localhost", 'root',nat_ip_cmd, None,  True).strip()
    list_host.append(cont_ip)
    list_host.append(nat_ip)
    for ip in list_host:
        m_type="controller"if cont_ip==ip else "nat"
    vm_utilization_rrd(ip,m_type)


def process_vmdaily_checks():
    """
    Check for the shutdown VM's and unused VM's and sends warning email to the user
    """
    logger.info("Entering VM's Daily Checks........")

    try:
        process_sendwarning_unusedvm()
        process_sendwarning_shutdownvm()
    except:
        log_exception()
        pass
    finally:
        db.commit()
        logger.debug("EXITING VM DAILY CHECKS........")


def process_unusedvm():
    """
    Purge/shutdown the unused VM's
    """
    logger.info("ENTERING PROCESS UNUSED VM ........")
    try:
        process_shutdown_unusedvm()
        process_purge_shutdownvm()
    except:
        log_exception()
        pass
    finally:
        db.commit()
        logger.debug("EXITING PROCESS UNUSED VM......")


def process_loadbalancer():
    logger.info("ENTERING PROCESS LOADBALANCER VM ........")
    try:
        (host_list,vm_list) = find_host_and_guest_list()
        loadbalance_vm(host_list,vm_list) 
    except:
        log_exception()
        pass
    finally:
        logger.debug("EXITING PROCESS LOADBALANCER VM......")

def _check_compile_folder(file_path):
    compile_cmd='gcc ' + str(file_path) + '/memhog.c -o  ' + str(file_path) +'/memhog'
    logger.debug(compile_cmd)
    if  "memhog" not in os.listdir(file_path):
        logger.debug("Memhog compiled file does not exist...Compiling memgog file...")
        os.system(compile_cmd)
        logger.debug("Compiled memgog file...")


def overload_memory():
    logger.debug("Executing overload memory task")
    file_path_row = db(db.constants.name=="memory_overload_file_path").select(db.constants.value).first()
    file_path = file_path_row.value
    logger.debug(type(file_path))
    host_ips_rows = db((db.host.status == HOST_STATUS_UP) & (db.host.host_ip == db.private_ip_pool.id)).select(db.private_ip_pool.private_ip)
    logger.debug(host_ips_rows)
    command2 = '/memhog >/memoryhog.out &'
    command3 = "ps -ef | grep memhog | grep -v grep | awk 'END{print FNR}'"
    for host_ip_row in host_ips_rows:
        logger.debug("overloading memory of"+str(host_ip_row))
        logger.debug(type(host_ip_row['private_ip']))
        _check_compile_folder(file_path)
        command1 = 'scp '+ str(file_path) +'/memhog root@'+ str(host_ip_row['private_ip']) +':/'
        logger.debug('executing' + command1) 
        ret = os.system(command1)
        logger.debug('os.system return value' + str(ret))
        output = execute_remote_cmd(host_ip_row['private_ip'], 'root', command3)
        ret1 = int(output[0])
        if(ret1 == 0):
            ret = execute_remote_cmd(host_ip_row['private_ip'], 'root', command2)
            logger.debug(ret)
    logger.debug("Completed overload memory task")


#host networking graph
def host_networking():
    logger.debug("collecting host networking data")
    active_host_list= db((db.host.status == HOST_STATUS_UP) & (db.host.host_ip == db.private_ip_pool.id)).select(db.private_ip_pool.private_ip)
    
    active_host_name=db(db.host.status == HOST_STATUS_UP).select(db.host.host_name)
    
    logger.debug( "active_host_list:" + str(active_host_list))
    logger.debug( "active_host_name:" + str(active_host_name))
    active_host_no=len(active_host_list)
    host_name_list=[]
    host_ip_list=[]
    for i in xrange(0,active_host_no):	
        host_ip_list.append(active_host_list[i].private_ip)
        host_name_list.append(active_host_name[i].host_name)
    logger.debug( host_ip_list)
    logger.debug( host_name_list)
    collect_data_from_host(host_ip_list,host_name_list)
    logger.debug("collected host networking data")    



     
# Defining scheduler tasks
from gluon.scheduler import Scheduler
vm_scheduler = Scheduler(db, tasks=dict(vm_task=process_vm_task_queue, 
                                        clone_task=process_clone_task,
                                        snapshot_vm=process_snapshot_vm,
                                        vm_sanity=vm_sanity_check,
                                        vnc_access=check_vnc_access,
                                        host_sanity=host_sanity_check,
                                        vm_util_rrd=vm_utilization_rrd,
                                        vm_daily_checks=process_vmdaily_checks,
                                        vm_garbage_collector=process_unusedvm,
                                        memory_overload=overload_memory,
                                        object_task=process_object_task,
                                        container_task=process_container_queue,
                                        networking_host=host_networking,
                                        rrd_task=task_rrd,
                                        vm_loadbalance=process_loadbalancer), 
                             group_names=
['vm_task','vm_sanity','host_task','vm_rrd','snapshot_task','object_task','host_network'])


midnight_time = request.now.replace(hour=23, minute=59, second=59)

vm_scheduler.queue_task(TASK_SNAPSHOT, 
                    pvars = dict(snapshot_type = SNAPSHOT_DAILY),
                    repeats = 0, # run indefinitely
                    start_time = midnight_time, 
                    period = 24 * HOURS, # every 24h
                    timeout = 5 * MINUTES,
                    uuid = UUID_SNAPSHOT_DAILY,
                    group_name = 'snapshot_task')

vm_scheduler.queue_task(TASK_SNAPSHOT, 
                    pvars = dict(snapshot_type = SNAPSHOT_WEEKLY),
                    repeats = 0, # run indefinitely
                    start_time = midnight_time, 
                    period = 7 * DAYS, # every 7 days
                    timeout = 5 * MINUTES,
                    uuid = UUID_SNAPSHOT_WEEKLY,
                    group_name = 'snapshot_task')

vm_scheduler.queue_task(TASK_SNAPSHOT, 
                    pvars = dict(snapshot_type = SNAPSHOT_MONTHLY),
                    repeats = 0, # run indefinitely
                    start_time = midnight_time, 
                    period = 30 * DAYS, # every 30 days
                    timeout = 5 * MINUTES,
                    uuid = UUID_SNAPSHOT_MONTHLY,
                    group_name = 'snapshot_task')

vm_scheduler.queue_task(TASK_VM_SANITY, 
                    repeats = 0, # run indefinitely
                    start_time = request.now, 
                    period = 30 * MINUTES, # every 30 minutes
                    timeout = 5 * MINUTES,
                    uuid = UUID_VM_SANITY_CHECK,
                    group_name = 'vm_sanity')

vm_scheduler.queue_task(TASK_HOST_SANITY, 
                    repeats = 0, # run indefinitely
                    start_time = request.now, 
                    period = 10 * MINUTES, # every 10 minutes
                    timeout = 5 * MINUTES,
                    uuid = UUID_HOST_SANITY_CHECK,
                    group_name = 'host_task')

# Adding task for scheduler to monitor unused VM's
vm_scheduler.queue_task(TASK_DAILY_CHECKS,
                    repeats = 0, # run indefinitely
                    start_time = request.now,
                    period = 24 * HOURS, # every 24h
                    timeout = 60 * MINUTES,
                    uuid = UUID_DAILY_CHECKS,
                    group_name = 'vm_sanity')


#Adding new task for scheduler to delete/shutdown unused VM's
vm_scheduler.queue_task(TASK_PURGE_UNUSEDVM,
                    repeats = 0, # run indefinitely
                    start_time = request.now,
                    period = 24 * HOURS, # every 24h
                    timeout = 60 * MINUTES,
                    uuid = UUID_PURGE_UNUSEDVM,
                    group_name = 'vm_sanity')

#Adding new task for scheduler to load_balance the VM by migrating them on other hosts.
vm_scheduler.queue_task(TASK_LOADBALANCE_VM,
                    repeats = 0, # run indefinitely
                    start_time = request.now,
                    period = 24 * HOURS, # every 24h
                    timeout = 10 * HOURS,
                    uuid = UUID_LOADBALANCE_VM,
                    group_name = 'vm_sanity')


vm_scheduler.queue_task('memory_overload',
                    repeats = 0, # run indefinitely
                    start_time = request.now,
                    period = 4 * HOURS, # every hour
                    timeout = 5 * MINUTES,
                    uuid = UUID_MEMORY_OVERLOAD,
                    group_name = 'host_task')

vm_scheduler.queue_task('networking_host',
                    repeats = 0, # run indefinitely
                    start_time = request.now,
                    period = 4 * HOURS, # every hour
                    timeout = 5 * MINUTES,
                    uuid = UUID_HOST_NETWORKING,
                    group_name = 'host_network')


vm_scheduler.queue_task("rrd_task",       
                    repeats = 0, # run indefinitely
                    start_time = request.now, 
                    period = 5 * MINUTES, # every 5 minutes
                    timeout = 5 * MINUTES,
                    uuid = UUID_RRD ,
                    group_name = 'vm_rrd')

active_host_list = db((db.host.status == HOST_STATUS_UP) & (db.host.host_ip == db.private_ip_pool.id)).select(db.private_ip_pool.private_ip)

for host in active_host_list:

    vm_scheduler.queue_task(TASK_RRD, 
                     pvars = dict(host_ip = host['private_ip']),
                     repeats = 0, # run indefinitely
                     start_time = request.now, 
                     period = 5 * MINUTES, # every 5 minutes
                     timeout = 5 * MINUTES,
                     uuid = UUID_VM_UTIL_RRD + "-" + str(host['private_ip']),
                    group_name = 'vm_rrd')

vm_scheduler.queue_task(TASK_VNC, 
                     repeats = 0, # run indefinitely
                     start_time = request.now, 
                     period = 5 * MINUTES, # every 5 minutes
                     timeout = 5 * MINUTES,
                     uuid = UUID_VNC_ACCESS,
                    group_name = 'vm_task')
