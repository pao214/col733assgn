# -*- coding: utf-8 -*-
###################################################################################
from gluon import current
from helper import execute_remote_cmd, get_constant, config, log_exception, \
    is_pingable, get_context_path
from libvirt import VIR_DOMAIN_SHUTOFF, VIR_DOMAIN_PAUSED, VIR_DOMAIN_RUNNING, \
    VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
from log_handler import logger
from vm_helper import find_new_host, launch_vm_on_host, revert
import commands
import csv
import libvirt
import math
import os
import paramiko

#Host Status
HOST_STATUS_DOWN = 0
HOST_STATUS_UP = 1
HOST_STATUS_MAINTENANCE = 2

HOST_TYPE_PHYSICAL = "Physical"
HOST_TYPE_VIRTUAL = "Virtual"


get_host_name={"10.0.0.5":"baadal_host_1","10.0.0.6":"baadal_host_2","10.0.0.7":"baadal_host_3","10.0.0.8":"baadal_host_4","10.0.0.9":"baadal_host_5","10.0.0.10":"baadal_host_6","10.0.0.11":"baadal_host_7","10.0.0.12":"baadal_host_8","10.0.0.13":"baadal_host_9"}

def check_host_status(host_ip):
    out=commands.getstatusoutput("ping -c 2 -W 1 " + host_ip)[0]
    logger.debug("Host Check command response for %s: %s" %(host_ip, str(out)))
    if(out == 0):
        if check_host_service_status(host_ip):
            return HOST_STATUS_UP
        else:
            return HOST_STATUS_DOWN
    else: 
        return HOST_STATUS_DOWN

def is_host_available(host_ip):
    try:
        execute_remote_cmd(host_ip,'root','pwd')
        return True
    except:
        return False

def get_host_mac_address(host_ip):
    command = "ifconfig -a | grep baadal-br-int | head -n 1"
    ret = execute_remote_cmd(host_ip, 'root',command)#Returns e.g. eth0      Link encap:Ethernet  HWaddr 18:03:73:0d:e4:49
    ret=ret.strip()
    mac_addr = ret[ret.rindex(' '):].lstrip()
    return mac_addr


def get_host_cpu(host_ip):
    command = "grep -c processor /proc/cpuinfo"
    ret = execute_remote_cmd(host_ip, 'root',command)
    return int(ret)
    

def get_host_ram(host_ip):
    command = "cat /proc/meminfo | grep MemTotal"
    ret = execute_remote_cmd(host_ip, 'root',command)#Returns e.g. MemTotal:       32934972 kB
    ram_in_kb = ret[ret.index(' '):-3].strip()
    ram_in_gb = int(math.ceil(float(ram_in_kb)/(1024*1024)))
    return ram_in_gb


def get_host_hdd(host_ip):
    
    command = "fdisk -l | egrep 'Disk.*bytes' | awk '{ sub(/,/,\"\"); sum +=$3;} END {print sum}'"
    ret = execute_remote_cmd(host_ip, 'root',command)#Returns e.g. 500.1 kB
    logger.debug("Host HDD is %s" %ret)
    hdd_in_gb = int(math.ceil(float(ret)))
    return hdd_in_gb


def get_host_type(host_ip):

    command="virt-what"
    ret=execute_remote_cmd(host_ip, 'root',command)
    return HOST_TYPE_VIRTUAL if ret else HOST_TYPE_PHYSICAL

def check_host_service_status(host_ip):
    #Check libvirt status
    command = "ps -ef | grep libvirtd | grep -v grep  | wc -l"
    ret = execute_remote_cmd(host_ip, 'root',command)
    if ret == 0 :
        logger.error("Critical: Libvirt service is not running on host " + host_ip)
        return False
    #Check OVS status
    command = "service openvswitch-switch status | grep -w 'running' | wc -l"
    ret = execute_remote_cmd(host_ip, 'root',command)
    if ret == 0 :
        logger.error("Critical: OVS switch is not running on host " + host_ip)
        return False
    return True
    
def host_status_sanity_check():
    for host in current.db().select(current.db.host.ALL):
        if host.status != HOST_STATUS_MAINTENANCE:
            host_status=check_host_status(host.host_ip.private_ip)
            if(host_status != host.status):
                logger.debug("Changing status of " + host.host_name +" to " + str(host_status))
                host.update_record(status=host_status)
                current.db.commit()
                if host_status == HOST_STATUS_DOWN:
                    respawn_dangling_vms(host.id)

#Respawn the VMs if the host is unexpectedly down 
def respawn_dangling_vms(host_id):
    
    vms = current.db(current.db.vm_data.host_id == host_id).select(current.db.vm_data.ALL)
    vm_image_location = get_constant('vmfiles_path') + get_constant('vms') + '/%s/%s.qcow2'
    for vm_data in vms:
        
        logger.debug('Re-spawning VM ' + vm_data.vm_identity)
        #Create a copy of existing image and rename it with '_old' suffix
        storage_type = config.get("GENERAL_CONF","storage_type")
        copy_command = 'ndmpcopy ' if storage_type == current.STORAGE_NETAPP_NFS else 'cp '
            
        ds_image_location = vm_data.datastore_id.path + get_constant('vms') + '/%s/%s.qcow2'
        command_to_execute = copy_command + ds_image_location%(vm_data.vm_identity, vm_data.vm_identity) + \
                                ' ' + ds_image_location%(vm_data.vm_identity, vm_data.vm_identity+'_old')

        execute_remote_cmd(vm_data.datastore_id.ds_ip, 
                           vm_data.datastore_id.username, 
                           command_to_execute, 
                           vm_data.datastore_id.password)
        logger.debug('Backup copy of the VM image cretaed successfully.')
        
        vm_properties = {}
        vm_properties['host'] = find_new_host(vm_data.RAM, vm_data.vCPU)
        vm_properties['ram'] = vm_data.RAM
        vm_properties['vcpus'] = vm_data.vCPU
        vm_properties['mac_addr'] = vm_data.private_ip.mac_addr
        vm_properties['vnc_port'] = vm_data.vnc_port
        vm_properties['template'] = current.db.template[vm_data.template_id]
        vm_properties['vlan_name'] = current.db(current.db.private_ip_pool.private_ip == vm_data.private_ip).select()[0].vlan.name

        # Re-spawn the VM on new host
        launch_vm_on_host(vm_data, vm_image_location%(vm_data.vm_identity, vm_data.vm_identity), vm_properties)
        vm_data.update_record(host_id = vm_properties['host'])
        
        #Find the most recent snapshot of the given VM; revert to the snapshot
        recent_snapshot = current.db(current.db.snapshot.vm_id == vm_data.id).select(orderby = ~current.db.snapshot.timestamp)[0]
        logger.debug('Reverting VM %s to snapshot %s' %(vm_data.vm_identity, recent_snapshot.snapshot_name))
        revert(dict(vm_id = vm_data.id, snapshot_id = recent_snapshot.id))

# Establishes a read only remote connection to libvirtd
# Finds out all domains running and not running
def get_host_domains(host_ip):
    try:
        conn = libvirt.openReadOnly('qemu+ssh://root@'+host_ip+'/system')
        domains=[]
        for domain_id in conn.listDomainsID():
            domains.append(conn.lookupByID(domain_id))
        
        for name in conn.listDefinedDomains():
            domains.append(conn.lookupByName(name))

        conn.close()
        return domains
    except:
        raise

# Finds if the given host has a running vm
def has_running_vm(host_ip):
    found=False
    if not check_host_status(host_ip):
        logger.debug("Host %s is down" %(host_ip))
        return False
    try:
        domains = get_host_domains(host_ip)
        for dom in domains:
            logger.debug("Checking "+str(dom.name()))
            if(dom.info()[0] != VIR_DOMAIN_SHUTOFF):
                found=True
    except:
        log_exception()
    return found


#Save Power, turn off extra hosts and turn on if required
def host_power_operation():
    logger.debug("\nIn host power operation function\n-----------------------------------\n")
    livehosts = current.db(current.db.host.status == HOST_STATUS_UP).select()
    freehosts=[]
    try:
        
        for host_data in livehosts:
            if not has_running_vm(host_data.host_ip.private_ip):
                freehosts.append(host_data.host_ip.private_ip)
        freehostscount = len(freehosts)
        if(freehostscount == 2):
            logger.debug("Everything is Balanced. Green Cloud :)")
        elif(freehostscount < 2):
            logger.debug("Urgently needed "+str(2-freehostscount)+" more live hosts.")
            newhosts = current.db(current.db.host.status == HOST_STATUS_DOWN).select()[0:(2-freehostscount)] #Select only Shutoff hosts
            for host_data in newhosts:
                logger.debug("Sending magic packet to "+host_data.host_name)
                host_power_up(host_data)
        elif(freehosts > 2):
            logger.debug("Sending shutdown signal to total "+str(freehostscount-2)+" no. of host(s)")
            extrahosts=freehosts[2:]
            for host_data in extrahosts:
                logger.debug("Moving any dead vms to first running host")
                migrate_all_vms_from_host(host_data.host_ip.private_ip)
                logger.debug("Sending kill signal to " + host_data.host_ip.private_ip)
                commands.getstatusoutput("ssh root@" + host_data.host_ip.private_ip + " shutdown -h now")
                host_data.update_record(status=HOST_STATUS_DOWN)
    except:
        log_exception()
    return

#Power up the host 
def host_power_up(host_data):
    try:
        host_ip = host_data.host_ip.private_ip
        if host_data.host_type == HOST_TYPE_VIRTUAL:
            execute_remote_cmd(host_ip, 'root', 'virsh start' + get_host_name[host_ip])
        else:
            setup_type = config.get("GENERAL_CONF","setup_type")
            if setup_type == "nic":
                ucs_management_ip = config.get("UCS_MANAGER_DETAILS","ucs_management_ip")
                ucs_user = config.get("UCS_MANAGER_DETAILS","ucs_user")
                ucs_password = config.get("UCS_MANAGER_DETAILS","ucs_password")
                host_ip=str(host_ip)
                server_num=host_ip.split('.')
                ucs_server_num=str(int(server_num[3])-20)
                logger.debug("ucs server number is :"+ucs_server_num)
                ssh = paramiko.SSHClient()
                ssh.load_system_host_keys()
                ssh.connect(ucs_management_ip,username=ucs_user,password=ucs_password)
                stdin, stdout,stderr=ssh.exec_command("scope org / ;  scope org IIT-Delhi ; scope service-profile Badal-Host"+ str(ucs_server_num) + " ; power up ; commit-buffer")  # @UnusedVariable
                output=stdout.readlines()               
                if len(output)!= 0:
                    logger.debug("Host not powered up . Command not run properly ")
            else:                        
                logger.debug('Powering up host with MAC ' + host_data.host_ip.mac_addr)
                commands.getstatusoutput( "wakeonlan " + host_data.host_ip.mac_addr)
        
        logger.debug("Host powered up successfully!!!")
    except:
        log_exception()


#Power down the host
def host_power_down(host_data):

    try:
        host_ip = host_data.host_ip.private_ip
        if host_data.host_type == HOST_TYPE_VIRTUAL:
            output = execute_remote_cmd(host_ip, 'root', 'virsh destroy' + get_host_name[host_ip])
        else:
            setup_type = config.get("GENERAL_CONF","setup_type")
            if setup_type == "nic":
                ucs_management_ip = config.get("UCS_MANAGER_DETAILS","ucs_management_ip")
                logger.debug(ucs_management_ip)
                logger.debug(type(ucs_management_ip))  
                ucs_user = config.get("UCS_MANAGER_DETAILS","ucs_user")
                logger.debug(ucs_user)
                logger.debug(type(ucs_user))
                ucs_password = config.get("UCS_MANAGER_DETAILS","ucs_password")
                logger.debug(ucs_password) 
                host_ip=str(host_ip)
                server_num=host_ip.split('.')
                ucs_server_num=str(int(server_num[3])-20)
                logger.debug("ucs server number is :"+ucs_server_num)
                ssh = paramiko.SSHClient()
                ssh.load_system_host_keys()
                ssh.connect(ucs_management_ip,username=ucs_user,password=ucs_password)                
                stdin, stdout,stderr=ssh.exec_command("scope org / ;  scope org IIT-Delhi ; scope service-profile Badal-Host"+ str(ucs_server_num) + " ; power down ; commit-buffer")  # @UnusedVariable
                output=stdout.readlines()
                if len(output)!= 0:
                    logger.debug("Host not powered up . Command not run properly ")
            else:                        
                output = execute_remote_cmd(host_ip, 'root', 'init 0')
        logger.debug(str(output) + ' ,Host shut down successfully !!!')
    except:
        log_exception()


#Migrate all running vms and redefine dead ones
def migrate_all_vms_from_host(host_ip):

    try:
        domains = get_host_domains(host_ip)
        for dom in domains:
            vm_details = current.db.vm_data(vm_identity=dom.name())
            if vm_details:
                if dom.info()[0] == VIR_DOMAIN_SHUTOFF:    #If the vm is in Off state, move it to host1
                    logger.debug("Moving "+str(dom.name())+" to another host")
                    add_migrate_task_to_queue(vm_details['id'])
                elif dom.info()[0] in (VIR_DOMAIN_PAUSED, VIR_DOMAIN_RUNNING):
                    logger.debug("Moving running vm "+str(dom.name())+" to appropriate host in queue")
                    add_migrate_task_to_queue(vm_details['id'], live_migration="on")
        
    except:
        log_exception()
    return

#Add migrate task to task_queue
def add_migrate_task_to_queue(vm_id, dest_host_id=None, live_migration=None):
    
    params={'vm_id' : vm_id, 'destination_host' : dest_host_id, 'live_migration' : live_migration}

    current.db.task_queue.insert(task_type=current.VM_TASK_MIGRATE_HOST,
                         requester_id=-1,
                         parameters=params, 
                         priority=1,  
                         status=1)

# Delete Orphan VM
def delete_orphan_vm(vm_name, host_id):
    
    host_details = current.db.host[host_id]
    connection_object = libvirt.open("qemu+ssh://root@" + host_details.host_ip.private_ip + "/system")
    domain = connection_object.lookupByName(vm_name)
    vm_state = domain.info()[0]
    if (vm_state == VIR_DOMAIN_RUNNING or vm_state == VIR_DOMAIN_PAUSED):
        logger.debug("VM is not shutoff. Shutting it off first.")
        domain.destroy()

    domain.undefineFlags(
            VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA)

    logger.debug(vm_name + " is deleted successfully.")
    
def get_active_hosts():
    
    return current.db(current.db.host.status == HOST_STATUS_UP).select(current.db.host.ALL)



########################host networking graph################################

def get_latency_btw_hosts(next_host_ip,host_ip):
    latency_cmd="netperf -t TCP_RR  -H"+str(next_host_ip)+ "| sed -n '7 p' | tr -s ' '| cut -f'6' -d' '"
    print("latency_cmd:" + str(latency_cmd))
    l_output=execute_remote_cmd(host_ip, "root", latency_cmd)
    lat=l_output
    if lat:
        
        latency=1/float(lat)
        
        print("latency between host is :"+ str(latency))
        ret=str(latency) 
    else:
        ret=str(lat)
    return ret

def get_bandwidth_of_host(host_ip):
  
    bandwidth_cmd='lshw | grep capacity | grep bit/s | sed -n "1 p" | tr -s " "  | cut -f"3" -d" "'
    bandwidth=execute_remote_cmd(host_ip,'root',bandwidth_cmd)
    m=str(bandwidth)
    q=m.replace("['",' ')    
    bandwidth=q.replace("']",' ')    
    return bandwidth


def get_throughput_btw_hosts(next_host_ip,host_ip):   

    throughput_cmd="netperf -t TCP_STREAM  -H "+str(next_host_ip)+"| sed -n '7 p'  | tr -s ' '  | cut -f'6' -d' '"
    throughput=execute_remote_cmd(host_ip, "root", throughput_cmd)
    ret=str(throughput).replace('\n','')
    return ret


def collect_data_from_host(host_ip_list,host_name_list):
    active_host_no=len(host_ip_list)
    
    data=[]
    
    indx_info=[]
    indx_info.insert(0,'current')
    indx_info.insert(1,'next')
    indx_info.insert(2,'latency')
    indx_info.insert(3,'throughput')
    data.insert(0,indx_info)

    for i in range(1,active_host_no+1):	
        host_ip=host_ip_list[i-1]

        if is_pingable(host_ip):
            
            for j in range(1,active_host_no+1):
                next_host_ip=host_ip_list[j-1]
                if is_pingable(next_host_ip):

                    row_info=[]
                    latency=get_latency_btw_hosts(next_host_ip,host_ip)
                    throughput=get_throughput_btw_hosts(next_host_ip,host_ip)
                    row_info.insert(0,str(i))
                    row_info.insert(1,str(j))
                    row_info.insert(2,latency)
                    row_info.insert(3,throughput)
                    data.insert(((active_host_no*(i-1))+j),row_info) 

                else :
                    logger.debug( "host is unreachable")
        else :
            logger.debug("host is unreachable")
   
    file_path = os.path.join(get_context_path(), 'static/sigma/graph.tsv')
    _file = open(file_path, 'w');
    writer = csv.writer(_file, dialect="excel-tab")
    for item in data:
        writer.writerow(item)
