from PIL import Image

import paho.mqtt.client as mqtt
import json
import logging
import time
import threading
import datetime
import numpy as np

import multiprocessing as mp

import os
from pathlib import Path

import paramiko

import pyopencl as cl

class BeamfinderWorker:
    def __init__(self, ithr, jobQueue, useOpenCL = False):
        self._frameOperations = [ self.op_testFrameOperation ]
        self._logger = logging.getLogger(__name__)
        self._logger.addHandler(logging.StreamHandler())
        self._logger.setLevel(logging.DEBUG)

        self._ithr = ithr
        self._jobQueue = jobQueue
        self._readConfigFile()

        self._useOpenCL = useOpenCL
        self._oclDevice = None
        self._oclPlatform = None
        while True:
            if useOpenCL:
                clPlatformName = None
                clDeviceName = None

                platform = None

                if "opencl" in self._configuration:
                    if "platform" in self._configuration["opencl"]:
                        clPlatformName = self._configuration["opencl"]["platform"]
                    if "device" in self._configuration["opencl"]:
                        clDeviceName = self._configuration["opencl"]["device"]

                # First query our platform (CPU / GPU)
                platforms = cl.get_platforms()
                if len(platforms) < 1:
                    self._logger.debug("No OpenCL platform available")
                    self._useOpenCL = False
                    break
                if clPlatformName is None:
                    platform = platforms[0]
                    self._logger.debug(f"No OpenCL platform specified, using {platform.name}")
                else:
                    for plat in platforms:
                        if plat.name == clPlatformName:
                            platform = plat
                            break
                    if platform is None:
                        self._logger.debug(f"Configured OpenCL platform {clPlatformName} not found")
                        self._useOpenCL = False
                        break

                # Then query the device ...
                devices = platform.get_devices()
                if len(devices) < 1:
                    self._logger.debug(f"No OpenCL device on platform {platform.name}")
                    self._useOpenCL = False
                    break
                if clDeviceName is None:
                    device = devices[0]
                    self._logger.debug(f"No OpenCL device specified, using {device.name}")
                else:
                    for dev in devices:
                        if dev.name == clDeviceName:
                            device = dev
                            break
                    if device is None:
                        self._logger.debug(f"Configured OpenCL device {clDeviceName} not found")
                        self._useOpenCL = False
                        break

                # Initialize OpenCL context and command queue ...
                context = cl.Context([device])
                clqueue = cl.CommandQueue(context, device)

                self._oclDevice = device
                self._oclPlatform = platform
                self._oclContext = context
                self._oclCQueue = clqueue

                self._logger.debug(f"Initialized context on platform {self._oclPlatform.name}: {self._oclDevice.name}")

                self.clKernels = {
                    'threshold' : {
                        'name' : "Thresholding",
                        'source' : '''//CL//
                            __kernel void threshold(
                                read_only image2d_t src,
                                write_only image2d_t dest,
                                float threshold
                            ) {
                                const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE | CLK_ADDRESS_CLAMP_TO_EDGE | CLK_FILTER_NEAREST;
                                int2 pos = (int2)(get_global_id(0), get_global_id(1));
                                float4 pix = read_imagef(src, sampler, pos);

                                if(pix.s0 < threshold) {
                                    pix.s0 = 0;
                                }

                                write_imagef(dest, pos, pix);
                            }'''
                    },
                }

                # Compile kernels ...
                self._logger.debug("Starting to compile OpenCL kernels")
                for krn in self.clKernels:
                    self._logger.debug(f"Compiling {self.clKernels[krn]['name']}")
                    self.clKernels[krn]['program'] = cl.Program(self._oclContext, self.clKernels[krn]['source']).build().threshold
                self._logger.debug("Done compiling OpenCL kernels")

                # Leave the while loop we use for flow control
                break

    def op_testFrameOperation(self, image = None, height = None, width = None, clImage = None):
        self._logger.debug("Called processing operation ...")
        pass

    def op_ThresholdImage(self, image = None, height = None, width = None, clImage = None):



    def _readConfigFile(self):
        # Every process has to read by himself ...
        cfgPath = os.path.join(Path.home(), ".config/thorbridge/beamfinder.conf")
        self._logger.debug(f"Trying to load configuration from {cfgPath}")
        cfgContent = None
        try:
            with open(cfgPath) as cfgFile:
                cfgContent = json.load(cfgFile)
        except FileNotFoundError:
            self._logger.warning(f"Failed to read configuration file from {cfgPath}")
            return False
        except JSONDecodeError as e:
            self._logger.error(f"Failed to process configuration file {cfgPath}: {e}")
            return False

        self._configuration = cfgContent
        self._logger.debug("Loaded configuration")

    def getFrame(self, msg):
        self._logger.debug("Requesting frame ...")
        # This method fetches the image specified in "msg". Depending on
        # configuration this is done either from the local machine or via
        # SFTP from a remote machine ...

        if "rawimagesftppath" in self._configuration['rawimages']:
            # Fetch via SFTP from remote machine into some temporary file
            # and delete afterwards ...
            try:
                stime = datetime.datetime.now(datetime.timezone.utc)
                self._logger.debug("Downloading frame ")

                sshKey = paramiko.RSAKey.from_private_key_file(self._configuration['rawimages']['rawimagesftppath']["keyfile"])
                sshClient = paramiko.SSHClient()
                sshClient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                sshClient.connect(self._configuration['rawimages']['rawimagesftppath']["host"], username = self._configuration['rawimages']['rawimagesftppath']["user"], pkey = sshKey)
                sftpClient = sshClient.open_sftp()
                self._logger.debug(f"Downloading {msg['imagefilename']} from {self._configuration['rawimages']['rawimagesftppath']['host']}")
                sftpClient.get(self._configuration['rawimages']['rawimagesftppath']['remotepath'] + msg['imagefilename'], self._configuration['rawimages']['rawimagesftppath']["temppath"] + msg['imagefilename'])
                sftpClient.close()
                sshClient.close()

                etime = datetime.datetime.now(datetime.timezone.utc)
                self._logger.debug(f"DONE Downloading {msg['imagefilename']} in {(etime - stime).total_seconds()} seconds")

                im = Image.open(self._configuration['rawimages']['rawimagesftppath']["temppath"] + msg['imagefilename'])
            except Exception as e:
                self._logger.warn(f"Failed to open image {msg['imagefilename']}: {e}")
                return None
        else:
            im = Image.open(msg['localfilename'])

        self._logger.debug(f"Loaded image with {len(im.getbands())} bands, {im.size[0]} x {im.size[1]} pixels large")

        if not self._useOpenCL:
            return im, im.size[0], im.size[1]
        else:
            # Load image into read only buffer (or read/write buffer) and return both ...
            imNp = np.array(im)
            self._logger.debug(f"Datatype in np array: {imNp.dtype}")
            imBuffer = cl.image_from_array(self._oclContext, imNp, len(im.getbands()), mode = 'r')
            self._logger.debug(f"Created OpenCL buffer for image {msg['imagefilename']}")

            return im, im.size[0], im.size[1], imBuffer

    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def _process_got_frame(self, workItem):
        if self._useOpenCL:
            im, h, w, clIm = self.getFrame(workItem)
            for op in self._frameOperations:
                op(image = im, height = h, width = w, clImage = clIm)
        else:
            im, h, w = self.getFrame(workItem)
            for op in self._frameOperations:
                op(image = im, height = h, width = w)
        if im is None:
            return


    def run(self):
        while True:
            workItem = self._jobQueue.get()
            if workItem is None:
                break

            # Handle work item ...
            if workItem['event'] == "storedRawFrame":
                self._logger.debug(f"WORKER: Handling raw frame {workItem}")
                self._process_got_frame(workItem)
            self._jobQueue.task_done()

        self._logger.debug(f"Worker {self._ithr} shutting down")
        self._jobQueue.task_done()

class BeamfinderMQTTHandler:
    def __init__(self, jobQueue, logger):
        self._jobQueue = jobQueue
        self._logger = logger
        self._terminate = False
        self._configuration = None
        if not self._readConfigFile():
            raise ValueError("Invalid configuration")

    def _readConfigFile(self):
        cfgPath = os.path.join(Path.home(), ".config/thorbridge/beamfinder.conf")
        self._logger.debug(f"Trying to load configuration from {cfgPath}")
        cfgContent = None
        try:
            with open(cfgPath) as cfgFile:
                cfgContent = json.load(cfgFile)
        except FileNotFoundError:
            self._logger.warning(f"Failed to read configuration file from {cfgPath}")
            return False
        except JSONDecodeError as e:
            self._logger.error(f"Failed to process configuration file {cfgPath}: {e}")
            return False

        # Validate configuration and check everything required is in there ...
        if not isinstance(cfgContent, dict):
            self._logger.error(f"Configuration file does not contains JSON object")
            return False

        if "mqtt" not in cfgContent:
            self._logger.error(f"Missing MQTT configuration in {cfgPath}")
            return False
        if not isinstance(cfgContent['mqtt'], dict):
            self._logger.error(f"MQTT configuration in {cfgPath} is not JSON object")
            return False
        if ("broker" not in cfgContent['mqtt']) or ("port" not in cfgContent['mqtt']) or ("user" not in cfgContent['mqtt']) or ("password" not in cfgContent['mqtt']) or ("basetopic" not in cfgContent['mqtt']):
            self._logger.error(f"Missing MQTT configuration broker, port, user, password or basetopic in {cfgPath}")
            return False
        try:
            cfgContent['mqtt']['port'] = int(cfgContent['mqtt']['port'])
            if (cfgContent['mqtt']['port'] < 1) or (cfgContent['mqtt']['port'] > 65535):
                raise ValueError("Invalid port number")
        except ValueError:
            self._logger.error(f"Port {cfgContent['mqtt']['port']} for MQTT service is invalid (integer between 1 and 65535)")
            return False

        if len(cfgContent['mqtt']['basetopic']) > 0:
            if cfgContent['mqtt']['basetopic'][-1] != '/':
                self._logger.warning("MQTT base topic not ending in trailing slash, appending")
                cfgContent['mqtt']['basetopic'] = cfgContent['mqtt']['basetopic'] + "/"

        self._configuration = cfgContent

        # Update / set MQTT topics
        self._mqttHandlers = MQTTPatternMatcher()
        self._mqttHandlers.registerHandler(f"{self._configuration['mqtt']['basetopic']}raw/stored", [ self._mqtt_raw_image_stored ])
        return True

    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def _mqtt_raw_image_stored(self, topic, msg):
        self._logger.debug(f"Received raw frame stored: {msg}")
        msg['event'] = "storedRawFrame"
        self._jobQueue.put(msg)

    def _mqtt_on_disconnect(self, client, userdata, rc):
        self._logger.debug("MQTT disconnected")
        if self._terminate:
            self._mqtt.loop_stop()

    def _mqtt_on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._logger.debug("Connected to MQTT server")

            # Subscribe to topics ...
            for topic in self._mqttHandlers._handlers:
                self._logger.debug(f"MQTT subscribing to {topic['pattern']}")
                client.subscribe(topic['pattern'])
        else:
            self._logger.warning(f"Failed to connect to MQTT server (code {rc})")

    def _mqtt_on_message(self, client, userdata, msg):
        self._logger.debug(f"MQTT-IN: {msg.topic}")

        try:
            msg.payload = json.loads(str(msg.payload.decode('utf-8', 'ignore')))
        except Exception as e:
            pass

        if self._mqttHandlers is not None:
            self._mqttHandlers.callHandlers(msg.topic, msg.payload, self._configuration['mqtt']['basetopic'])
        else:
            self._logger.debug(f"MQTT-IN dropping message on {msg.topic}")

    def run(self):
        self._logger.debug("Starting MQTT client")
        self._mqtt = mqtt.Client()
        self._mqtt.on_connect = self._mqtt_on_connect
        self._mqtt.on_message = self._mqtt_on_message
        self._mqtt.on_disconnect = self._mqtt_on_disconnect
        if (self._configuration['mqtt']['user'] is not None) and (self._configuration['mqtt']['password'] is not None):
            self._mqtt.username_pw_set(self._configuration['mqtt']['user'], self._configuration['mqtt']['password'])
        self._mqtt.connect(self._configuration['mqtt']['broker'], self._configuration['mqtt']['port'])
        self._logger.debug("Entering MQTT loop")
        self._mqtt.loop_forever()
        self._logger.debug("Shutting down MQTT handler")








class MQTTPatternMatcher:
    def __init__(self):
        self._handlers = []
        self._idcounter = 0

    def registerHandler(self, pattern, handler):
        self._idcounter = self._idcounter + 1
        self._handlers.append({ 'id' : self._idcounter, 'pattern' : pattern, 'handler' : handler })
        return self._idcounter

    def removeHandler(self, handlerId):
        newHandlerList = []
        for entry in self._handlers:
            if entry['id'] == handlerId:
                continue
            newHandlerList.append(entry)
        self._handlers = newHandlerList

    def _checkTopicMatch(self, filter, topic):
        filterparts = filter.split("/")
        topicparts = topic.split("/")

        # If last part of topic or filter is empty - drop ...
        if topicparts[-1] == "":
            del topicparts[-1]
        if filterparts[-1] == "":
            del filterparts[-1]

        # If filter is longer than topics we cannot have a match
        if len(filterparts) > len(topicparts):
            return False

        # Check all levels till we have a mistmatch or a multi level wildcard match,
        # continue scanning while we have a correct filter and no multi level match
        for i in range(len(filterparts)):
            if filterparts[i] == '+':
                continue
            if filterparts[i] == '#':
                return True
            if filterparts[i] != topicparts[i]:
                return False

        if len(topicparts) != len(filterparts):
            return False

        # Topic applies
        return True

    def callHandlers(self, topic, message, basetopic = "", stripBaseTopic = True):
        topic_stripped = topic
        if basetopic != "":
            if topic.startswith(basetopic) and stripBaseTopic:
                topic_stripped = topic[len(basetopic):]

        for regHandler in self._handlers:
            if self._checkTopicMatch(regHandler['pattern'], topic):
                if isinstance(regHandler['handler'], list):
                    for handler in regHandler['handler']:
                        handler(topic_stripped, message)
                elif callable(regHandler['handler']):
                    regHandler['handler'](topic_stripped, message)

# Startup methods just bootstrap objects

def processingStartup(ithr, jobQueue):
    with BeamfinderWorker(ithr, jobQueue, useOpenCL = True) as worker:
        worker.run()

def mainStartup(nProcesses = 1):
    multictx = mp.get_context("spawn")
    jobQueue = multictx.JoinableQueue()
    improcesses = []

    for ithr in range(nProcesses):
        improcesses.append(multictx.Process(target=processingStartup, args=(ithr, jobQueue)))
        improcesses[len(improcesses)-1].start()

    mainLogger = logging.getLogger(__name__)
    mainLogger.addHandler(logging.StreamHandler())
    mainLogger.setLevel(logging.DEBUG)

    # Launch our MQTT handler ...
    mainLogger.debug("Launching MQTT handler")
    try:
        with BeamfinderMQTTHandler(jobQueue, mainLogger) as mqttHandler:
            mqttHandler.run()
    except ValueError:
        # In case of configuration error this exception is raised and
        # we shut down all or our threads again
        pass

    # We shutdown the workers by transmitting a "None" and use the join property
    # of the queue to shutdown

    mainLogger.debug("Requesting worker shutdown")
    for i in range(nProcesses):
        jobQueue.put(None)

    mainLogger.debug("Waiting for worker shutdown")
    jobQueue.join()
    mainLogger.debug("All workers finished, shutting down")

if __name__ == "__main__":
    mainStartup()
