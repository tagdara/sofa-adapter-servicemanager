#!/usr/bin/python3

import sys, os
# Add relative paths for the directory where the adapter is located as well as the parent
sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__),'../../base'))

from sofabase import sofabase
from sofabase import adapterbase
from sofacollector import SofaCollector

import devices

import math
import random
from collections import namedtuple

import json
import asyncio
import aiohttp
import subprocess
import pystemd
from pystemd.systemd1 import Unit
import datetime

class servicemanager(sofabase):
    
    class EndpointHealth(devices.EndpointHealth):
        
        @property            
        def connectivity(self):
            if 'service' in self.nativeObject and 'ActiveState' in self.nativeObject['service']:
                if self.nativeObject['service']['ActiveState']=='active':
                    return 'OK'
            return 'UNREACHABLE'

    class AdapterHealth(devices.AdapterHealth):
        
        @property
        def controller(self):
            return "AdapterHealth"
    
        @property
        def port(self):
            if 'rest' in self.nativeObject and 'port' in self.nativeObject['rest']:
                return self.nativeObject['rest']['port']
            else:
                return ''

        @property
        def address(self):
            if 'rest' in self.nativeObject and 'address' in self.nativeObject['rest']:
                return self.nativeObject['rest']['address']
            else:
                return ''

        @property
        def url(self):
            if 'rest' in self.nativeObject and 'port' in self.nativeObject['rest']:
                return 'http://%s:%s' % (self.nativeObject['rest']['address'], self.nativeObject['rest']['port'])
            else:
                return ''


        @property
        def logged(self):
            if 'state' in self.nativeObject and 'logged' in self.nativeObject['state']:
                return self.nativeObject['state']['logged']
            else:
                return {'ERROR':0, 'INFO':0}

        @property
        def startup(self):
            try:
                if 'service' in self.nativeObject and 'ActiveState' in self.nativeObject['service']:
                    if self.nativeObject['service']['ActiveState']=='active':
                        return datetime.datetime.fromtimestamp(self.nativeObject['service']['ExecMainStartTimestamp']).isoformat()
                if 'rest' in self.nativeObject and 'startup' in self.nativeObject['rest']:
                    return self.nativeObject['rest']['startup']
            except:
                self.log.error('!! Error getting startup time', exc_info=True)
                
            return ''


    class PowerController(devices.PowerController):

        @property            
        def powerState(self):
            if 'service' in self.nativeObject and 'ActiveState' in self.nativeObject['service']:
                if self.nativeObject['service']['ActiveState']=='active':
                    return 'ON'
            return 'OFF'
            

        async def TurnOn(self, correlationToken='', **kwargs):
            try:
                self.nativeObject['logged']={'ERROR':0, 'INFO':0}
                stdoutdata = subprocess.getoutput("/opt/sofa-server/svc %s" % self.nativeObject['name'])
                #return web.Response(text=stdoutdata)
                return self.device.Response(correlationToken)
            except:
                self.log.error('!! Error restarting adapter', exc_info=True)
                return self.device.Response(correlationToken)

        async def TurnOff(self, correlationToken='', **kwargs):
            try:
                pids_output=subprocess.check_output(["pgrep","-f","sofa-server/adapters/%s/" % self.nativeObject['name']])
                pids=pids_output.decode().strip().split('\n')
                stdoutdata=""
                for pid in pids:
                    stdoutdata += subprocess.getoutput("kill -9 %s" % pid)
                self.log.info('.. results from kill %s (%s): %s' % (self.nativeObject['name'], pids, stdoutdata))
                #return web.Response(text=stdoutdata)
                return self.device.Response(correlationToken)
            except:
                self.log.error('!! Error stopping adapter', exc_info=True)
                return self.device.Response(correlationToken)  
    
    class adapterProcess(SofaCollector.collectorAdapter):
    
        def __init__(self, log=None, loop=None, dataset=None, notify=None, request=None, **kwargs):
            self.dataset=dataset
            self.log=log
            self.notify=notify
            self.polltime=10
            self.loop=loop
            self.dataset.nativeDevices['adapters']={}
            
        async def start(self):
            self.log.info('.. Starting adapter')
            await self.add_defined_adapters()
            await self.poll_loop()
            
        async def poll_loop(self):
            while True:
                try:
                    #self.log.info("Polling data")
                    await self.adapter_checker()
                    await asyncio.sleep(self.polltime)
                except:
                    self.log.error('!! Error polling for data', exc_info=True)
                    
        # Utility Functions
 
        async def add_defined_adapters(self):
            
            try:
                for adapter in self.dataset.config['adapters']:
                    newadapter={"name":adapter, "state":{}, "service":{}, "rest": {}}
                    await self.dataset.ingest({'adapters': { adapter : newadapter}})
            except:
                self.log.error('!! Error populating adapters', exc_info=True)
        
        async def adapter_checker(self):
            
            try:
                workingadapters=self.dataset.baseConfig['adapters']
                for adapter in workingadapters:
                    adapterstate={"state":{}, "service":{}, "rest": {}}
                    if adapter in self.dataset.nativeDevices['adapters']:
                        if 'port' in self.dataset.nativeDevices['adapters'][adapter]['rest']:
                            adapterstate['state']=await self.get_adapter_status(adapter)
                    else:
                        self.log.warning('.. adapter %s not in %s' % (adapter, self.dataset.nativeDevices['adapters']))
                    adapterstate['service']=await self.get_service_status(adapter)
                    #adapterstate['rest']=self.dataset.nativeDevices['adapters'][adapter]
                    
                    self.log.info('.. adapter check %s - %s' % (adapter, adapterstate))
                    await self.dataset.ingest({'adapters': { adapter : adapterstate}})
                    
            except:
                self.log.error('!! Error listing adapters', exc_info=True)
        
        async def virtualAddAdapter(self, adapter, adapterdata):
            
            try:
                #self.log.info('Getting discovered adapter status for %s' % adapter)
                adapterstate=await self.get_adapter_status(adapter)
                adapterstate['service']=await self.get_service_status(adapter)
                adapterstate['rest']=self.dataset.adapters[adapter]
                await self.dataset.ingest({'adapters': { adapter : adapterstate}})
            except:
                self.log.info('!! Error getting adapter status after discovery: %s' % adapter, exc_info=True)

        async def virtualUpdateAdapter(self, adapter, adapterdata):
            
            try:
                self.log.info('.. getting updated adapter status for %s - %s' % (adapter,adapterdata))
                await self.get_adapter_status(adapter)
            except:
                self.log.info('!. Error updating adapter status after discovery: %s' % adapter, exc_info=True)

        # Adapter Overlays that will be called from dataset
        async def addSmartDevice(self, path):
            
            try:
                if path.split("/")[1]=="adapters":
                    nativeObject=self.dataset.getObjectFromPath(self.dataset.getObjectPath(path))
                    #self.log.info('native: %s %s' % (path,nativeObject))
                    if nativeObject['name'] not in self.dataset.localDevices: 
                        deviceid=path.split("/")[2]
                        device=devices.alexaDevice('servicemanager/adapters/%s' % deviceid, deviceid, displayCategories=['ADAPTER'], adapter=self)
                        device.PowerController=servicemanager.PowerController(device=device)
                        device.AdapterHealth=servicemanager.AdapterHealth(device=device)
                        device.EndpointHealth=servicemanager.EndpointHealth(device=device)
                        return self.dataset.newaddDevice(device) 
            except:
                self.log.error('!! Error defining smart device', exc_info=True)
                return False

        
        async def get_adapter_status(self, adaptername):
            
            try:
                result=""
                url = 'http://%s:%s/status' % (self.dataset.adapters[adaptername]['address'], self.dataset.adapters[adaptername]['port'])
                async with aiohttp.ClientSession() as client:
                    async with client.get(url) as response:
                        result=await response.read()
                        return json.loads(result.decode())
                        
            except aiohttp.client_exceptions.ClientConnectorError:
                self.log.warn('!! Connection error trying to get status for adapter %s at %s' % (adaptername, url))
                return {}
            except aiohttp.client_exceptions.ClientOSError:
                self.log.warn('!! Connection error trying to get status for adapter %s at %s' % (adaptername, url))
                return {}

            except:
                self.log.error('!! Error getting status for adapter %s at %s = %s' % (adaptername, url, result), exc_info=True)
                return {}

        async def get_service_status(self, adaptername):
            
            try:
                unit = Unit(str.encode('sofa-%s.service' % adaptername))
                unit.load()
                unit.Unit.ActiveState
                unit.Unit.SubState
                #unit.Unit.stop()
                processes=unit.Service.GetProcesses()
                mainprocess=""
                for process in processes:
                    if process[1]==unit.Service.MainPID:
                        mainprocess=process[2].decode()
                return {
                    "ActiveState": unit.Unit.ActiveState.decode(), 
                    "SubState": unit.Unit.SubState.decode(), 
                    "ExecMainPID": unit.Service.MainPID, 
                    "Process": mainprocess,
                    "ExecMainStartTimestamp": int(str(unit.Service.ExecMainStartTimestamp)[:10]), 
                    "LoadState": unit.Unit.LoadState.decode()
                }
            except:
                self.log.error('!! Error getting adapter service status', exc_info=True)
                return {}

                
        async def old_get_service_status(self, adaptername):
            
            try:
                keep=['WatchdogTimestamp', 'ExecMainStartTimestamp', 'LoadState', 'Result', 'ExecMainPID','ActiveState', 'SubState']
                
                key_value = subprocess.check_output(["systemctl", "show", "sofa-%s" % adaptername], universal_newlines=True).split('\n')
                json_dict = {}
                for entry in key_value:
                    kv = entry.split("=", 1)
                    if len(kv) == 2:
                        if kv[0] in keep:
                            json_dict[kv[0]] = kv[1]
                return json_dict        
            except:
                self.log.error('!! Error getting adapter service status', exc_info=True)
                return {}
                
            
        async def adapterRestartHandler(self, adaptername):
            
            try:
                stdoutdata = subprocess.getoutput("/opt/sofa-server/svc %s" % adaptername)
            except:
                self.log.error('!! Error restarting adapter', exc_info=True)


if __name__ == '__main__':
    adapter=servicemanager(name='servicemanager')
    adapter.start()
