#!/usr/bin/env python
#
# Copyright 2015 Ravello Systems Inc.
#
# Based on fakebmc Copyright 2015 Lenovo
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
__author__ = 'benoit.canet@nodalink.com'

# This is a virtual IPMI BMC doing power query against the Ravello API server
# to play:
# python2.x ravellobmc.py --help
# python2.x ravellobmc.py arguments
#
# ipmitool -I lanplus -U admin -P password -H 127.0.0.1 power status
# Chassis Power is off
# # ipmitool -I lanplus -U admin -P password -H 127.0.0.1 power on
# Chassis Power Control: Up/On
# # ipmitool -I lanplus -U admin -P password -H 127.0.0.1 power status
# Chassis Power is on

import argparse
import logging
import pyghmi.ipmi.bmc as bmc
import pyghmi.ipmi.command as ipmicommand
import signal
import sys
import threading
import time
from pprint import pprint

from ravello_sdk import RavelloClient

IPMI_PORT = 623

global my_bmc
global my_thread
global my_lock

def start_bmc(args, ipmi_password, api_password):
    global my_bmc
    global my_lock

    my_lock = threading.Lock()
    my_lock.acquire()

    my_bmc = RavelloBmc({'admin': ipmi_password},
                        port=IPMI_PORT,
                        address=args.address,
                        aspect=args.aspect,
                        username=args.api_username,
                        password=api_password,
                        app_name=args.app_name,
                        vm_name=args.vm_name)

    if not my_bmc.connect():
        my_lock.release()
        msg = "Failed to connect to API server. Exiting"
        logging.error(msg)
        print(msg)
        sys.exit(1)

    # We must release the lock here to avoid a dead lock since
    # bmc.listen() is a busy loop
    my_lock.release()

    my_bmc.listen()


class RavelloBmc(bmc.Bmc):
    """Ravello IPMI virtual BMC."""

    def get_vm(self, application, name):
        """Get a VM by name."""
        vms = application.get(self._aspect, {}).get('vms', [])
        for vm in vms:
            if vm['name'] == name:
                return vm

        msg = 'vm not found: {0}'.format(name)
        logging.error(msg)
        raise ValueError(msg)

    def connect(self):
        """Connect to the Ravello API server with the given credentials."""
        try:
            self._client = RavelloClient()
            #self._client.login(self._username, self._password)
            self._client = RavelloClient(eph_token = self._password)
            c = self._client
            self._app = c.get_application_by_name(self._app_name,
                                                  aspect=self._aspect)
            self._vm = self.get_vm(self._app, self._vm_name)
            return True
        except Exception as e:
            msg = "Exception while connecting to API server:" + str(e)
            logging.error(msg)
            print(msg)
            return False

    def __init__(self, authdata, port, address, aspect, username, password,
                 app_name, vm_name):
        """Ravello virtual BMC constructor."""
        self._client = None
        super(RavelloBmc, self).__init__(authdata,
                                         address=address,
                                         port=port)
        self._aspect = aspect
        self._username = username
        self._password = password
        self._app_name = app_name
        self._vm_name = vm_name

    def disconnect(self):
        """Disconnect from the Ravello API server."""
        if not self._client:
            return

        self._client.logout()
        self._client.close()

    def __del__(self):
        """Ravello virtual BMC destructor."""
        self.disconnect()

    # Disable default BMC server implementations

    def cold_reset(self):
        """Cold reset reset the BMC so it's not implemented."""
        raise NotImplementedError

    def get_boot_device(self):
        """Get the boot device of a Ravello VM."""

        try:
            # query the vm again to have an updated device
            c = self._client
            self._app = c.get_application_by_name(self._app_name,
                                                  aspect=self._aspect)
            self._vm = self.get_vm(self._app, self._vm_name)

            if self._vm['bootOrder'][0] == "DISK":
                return 0x08
            elif self._vm['bootOrder'][0] == "CDROM":
                return 0x04
        except Exception as e:
            logging.error(self._vm_name + ' get_boot_device:' + str(e))
            return 0xce

        return 0x04

    def get_system_boot_options(self, request, session):
        logging.info(self._vm_name + " get boot options")
        if request['data'][0] == 5:  # boot flags
            try:
                bootdevice = self.get_boot_device()
                logging.info(self._vm_name + ' bootdevice = ' + bootdevice)
            except NotImplementedError:
                session.send_ipmi_response(data=[1, 5, 0, 0, 0, 0, 0])
            if (type(bootdevice) != int and
                    bootdevice in ipmicommand.boot_devices):
                bootdevice = ipmicommand.boot_devices[bootdevice]
            paramdata = [1, 5, 0b10000000, bootdevice, 0, 0, 0]
            return session.send_ipmi_response(data=paramdata)
        else:
            session.send_ipmi_response(code=0x80)


    def set_boot_device(self, bootdevice):
        try:
          # query the vm again to have an updated device
          c = self._client
          self._app = c.get_application_by_name(self._app_name)
          appid = self._app['id']
          for vm in self._app['design']['vms']:
            change = False
            if vm['name'] == self._vm_name:
              logging.info(self._vm_name + " Boot device requested: " + str(bootdevice))
              if bootdevice == "network":
                vm['bootOrder'] = [ "CDROM", "DISK" ]
                change = True
              elif bootdevice == "hd":
                vm['bootOrder'] = [ "DISK", "CDROM" ]
                change = True
            if change == True:
              #pprint (self._app)
              logging.info("Updating app " + self._app_name + " vm " + self._vm_name + " with boot device " + str(bootdevice))
              ap = self._client.update_application(self._app)
              if ap['published']:
                logging.info("Updating app " + str(appid))
                self._client.publish_application_updates(appid)
        except Exception as e:
            logging.error(self._vm_name + ' set_boot_device:' + str(e))
            return 0xce

    def set_kg(self, kg):
        """Desactivated IPMI call."""
        raise NotImplementedError

    def set_system_boot_options(self, request, session):
        logging.info("set boot options vm:" + self._vm_name)
        if request['data'][0] in (0, 3, 4):
            logging.info("Ignored RAW option " + str(request['data']) + " for: " + self._vm_name + "... Smile and wave.")
            # for now, just smile and nod at boot flag bit clearing
            # implementing it is a burden and implementing it does more to
            # confuse users than serve a useful purpose
            session.send_ipmi_response(code=0x00)
        elif request['data'][0] == 5:
            bootdevice = (request['data'][2] >> 2) & 0b1111
            logging.info("Got set boot device for " + self._vm_name + " to " + str(request['data'][2]))
            try:
                bootdevice = ipmicommand.boot_devices[bootdevice]
                logging.info("Setting boot device for " + self._vm_name + " to " + bootdevice)
            except KeyError:
                session.send_ipmi_response(code=0xcc)
                return
            self.set_boot_device(bootdevice)
            session.send_ipmi_response()
        else:
            raise NotImplementedError

    def power_reset(self):
        """Reset a VM."""
        # Shmulik wrote "Currently, limited to: "chassis power on/off/status"
        raise NotImplementedError

    # Implement power state BMC features
    def get_power_state(self):
        """Get the power state of a Ravello VM."""

        try:
            # query the vm again to have an updated status
            c = self._client
            self._app = c.get_application_by_name(self._app_name,
                                                  aspect=self._aspect)
            self._vm = self.get_vm(self._app, self._vm_name)

            if self._vm['state'] == 'STARTED' or self._vm['state'] == 'STARTING' or self._vm['state'] == 'STOPPING':
                logging.info('returning power state ON for vm ' + self._vm_name)
                return "on"
            else:
                logging.info('returning power state OFF for vm ' + self._vm_name)
                return "off"

        except Exception as e:
            logging.error(self._vm_name + ' get_power_state:' + str(e))
            return 0xce

        return "off"

    def power_off(self):
        """Cut the power without waiting for clean shutdown."""
        logging.info("Power OFF called for VM " + self._vm_name + " with state: " + self._vm['state'])
        # query the vm again to have an updated status
        c = self._client
        self._app = c.get_application_by_name(self._app_name,
                                              aspect=self._aspect)
        self._vm = self.get_vm(self._app, self._vm_name)
        if self._vm['state'] == 'STARTED':
          try:
              #self._client.poweroff_vm(self._app, self._vm)
              self._client.stop_vm(self._app, self._vm)
          except Exception as e:
              logging.error(self._vm_name + ' power_off:' + str(e))
              return 0xce
        elif self._vm['state'] == 'STOPPING' or self._vm['state'] == 'STARTING':
          return 0xc0
        else:
          return 0xce

    def power_on(self):
        """Start a vm."""
        logging.info("Power ON called for VM " + self._vm_name + " with state: " + self._vm['state'])
        # query the vm again to have an updated status
        c = self._client
        self._app = c.get_application_by_name(self._app_name,
                                              aspect=self._aspect)
        self._vm = self.get_vm(self._app, self._vm_name)
        if self._vm['state'] == 'STOPPED':
          try:
              self._client.start_vm(self._app, self._vm)
          except Exception as e:
              logging.error(self._vm_name + ' power_on:' + str(e))
              return 0xce
        elif self._vm['state'] == 'STOPPING' or self._vm['state'] == 'STARTING':
          return 0xc0
        else:
          return 0xce

    def power_shutdown(self):
        """Gently power off while waiting for clean shutdown."""
        logging.info("Power SHUTDOWN called for VM " + self._vm_name + " with state: " + self._vm['state'])
        # query the vm again to have an updated status
        c = self._client
        self._app = c.get_application_by_name(self._app_name,
                                              aspect=self._aspect)
        self._vm = self.get_vm(self._app, self._vm_name)
        if self._vm['state'] == 'STARTED':
          try:
              self._client.stop_vm(self._app, self._vm)
          except Exception as e:
              logging.error(self._vm_name + ' power_shutdown:' + str(e))
              return 0xce
        elif self._vm['state'] == 'STOPPING' or self._vm['state'] == 'STARTING':
          return 0xc0
        else:
          return 0xce

def parse_args():
    parser = argparse.ArgumentParser(
        prog='ravellobmc',
        description='The Ravello virtual BMC',
    )

    # Use a compact format for declaring command line options
    arg_list = []
    arg_list.append(['address', 'Address to listen on; defaults to localhost'])
    arg_list.append(['aspect', 'Aspect'])
    arg_list.append(['api-username', 'User name (use "token" for ephemeral access)'])
    arg_list.append(['app-name', 'Name of the Ravello application'])
    arg_list.append(['vm-name', 'Name of the VMX virtual machine'])
    arg_list.append(['ipmi-password', 'IPMI Password'])
    arg_list.append(['api-password', 'API Password'])

    # expand the list of command line options
    for arg in arg_list:
        parser.add_argument('--%s' % arg[0],
                            dest=arg[0].replace('-', '_'),
                            type=str,
                            help=arg[1],
                            required=True)

    parser.add_argument('--debug',
                        dest='debug',
                        action='store_true',
                        help='Enable Ravello SDK debugging')

    return parser.parse_args()


def exit_signal(signal, frame):
    global my_bmc
    global my_thread
    global my_lock
    my_thread._Thread__stop()
    my_thread.join()

    my_lock.acquire()
    my_bmc.disconnect()
    my_lock.release()

    sys.exit(0)

if __name__ == '__main__':
    args = parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    # Ask for password on stdin so they do not appears in process list
    #print("Please enter IPMI proxy password")
    #ipmi_password = sys.stdin.readline().strip()
    ipmi_password = args.ipmi_password

    #print("Please enter Ravello API server password")
    #api_password = sys.stdin.readline().strip()
    api_password = args.api_password

    global my_thread
    my_thread = threading.Thread(target=start_bmc,
                                 args=(args, ipmi_password, api_password))
    my_thread.start()

    signal.signal(signal.SIGINT,  exit_signal)

    while True:
        time.sleep(1)
