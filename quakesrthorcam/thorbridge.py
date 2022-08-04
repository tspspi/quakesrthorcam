from thorcam.camera import ThorCam

from PIL import Image

import paho.mqtt.client as mqtt
import json
import logging
import time
import threading
import datetime

import os
from pathlib import Path


class ThorCamWrapper(ThorCam):
    def __init__(self, bridge = None):
        self._serials = []
        if bridge is not None:
            self._logger = bridge._logger
            self._bridge = bridge
        else:
            self._bridge = None
            self._logger = logging.getLogger(__name__)
            self._logger.addHandler(logging.StreamHandler())
            self._logger.setLevel(logging.DEBUG)

        self.state = 0
        self._logger.debug("Starting ThorCam process")
        self.start_cam_process()
        time.sleep(5)
        self.state = 1

    def shutdown(self):
        if self.cam_open:
            self._logger.debug("Closing ThorCam")
            self.close_camera()
        if self.process_connected:
            self._logger.debug("Shutting down ThorCam process")
            self.stop_cam_process(join = True, kill_delay = 30)

    def periodic(self):
        # This function is called for any periodic tasks such as querying
        # serials whenever the process has started
        if self.state == 0:
            return
        if self.state == 1:
            # First we check in our serials (if present) if we found a camera
            # that we want to use. If not we refresh cameras ...
            if (self._serials is not None) and (len(self._serials) > 0):
                if self._bridge is not None:
                    if self._bridge._configuration is not None:
                        # We default to the first serial in case none is specified ...
                        usedSerial = self._serials[0]

                        if ("thorcam" in self._bridge._configuration) and isinstance(self._bridge._configuration['thorcam'], dict) and ("serial" in self._bridge._configuration['thorcam']):
                            usedSerial = self._bridge._configuration['thorcam']['serial']

                        self._logger.debug(f"Using ThorCam {usedSerial}")
                        self.state = 2
                        self.open_camera(usedSerial)
                    else:
                        # Wait for next periodic run when we then have some configuration - hopefully
                        self.refresh_cameras()
                else:
                    usedSerial = self._serials[0]
                    self._logger.debug(f"Using ThorCam {usedSerial} without bridge")
                    self.state = 2
                    self.open_camera(usedSerial)
            else:
                self._logger.debug("Refreshing camera serials ...")
                # On periodic we update the serials list
                self.refresh_cameras()
        if self.state == 3:
            # Simply start camera for now when we are in configured state ...
            self._logger.debug("Starting camera stream")
            self.play_camera()
            self.state = 4

    def received_camera_response(self, msg, value):
        super(ThorCamWrapper, self).received_camera_response(msg, value)

        if msg == "serials":
            if len(value) > 0:
                self._logger.debug(f"Updated camera serials: {value}")
                self._serials = value
            return
        if msg == "cam_open":
            self._logger.debug("Camera opened successfully")
            if ("thorcam" in self._bridge._configuration) and isinstance(self._bridge._configuration['thorcam'], dict) and ("trigger" in self._bridge._configuration['thorcam']) and (isinstance(self._bridge._configuration['thorcam']['trigger'], dict)) and ("hardware" in self._bridge._configuration['thorcam']['trigger']):
                if self._bridge._configuration['thorcam']['trigger']['hardware']:
                    if "HW Trigger" not in self.supported_triggers:
                        self._logger.error("Configuration requests hardware trigger but not supported by camera")
                    else:
                        self._logger.debug("Setting hardware trigger")
                        self.set_setting("trigger_type", "HW Trigger")
                else:
                    if "SW Trigger" not in self.supported_triggers:
                        self._logger.error("Configuration requests software trigger but not supported by camera")
                    else:
                        self._logger.debug("Setting software trigger")
                        self.set_setting("trigger_type", "SW Trigger")
            if ("thorcam" in self._bridge._configuration) and isinstance(self._bridge._configuration['thorcam'], dict) and ("trigger" in self._bridge._configuration['thorcam']) and (isinstance(self._bridge._configuration['thorcam']['trigger'], dict)) and ("count" in self._bridge._configuration['thorcam']['trigger']) and (isinstance(self._bridge._configuration['thorcam']['trigger']['count'], int)):
                self._logger.debug(f"Setting trigger count to {self._bridge._configuration['thorcam']['trigger']['count']}")
                self.set_setting("trigger_count", self._bridge._configuration['thorcam']['trigger']['count'])

            if ("thorcam" in self._bridge._configuration) and isinstance(self._bridge._configuration['thorcam'], dict) and ("exposure" in self._bridge._configuration['thorcam']) and (isinstance(self._bridge._configuration['thorcam']['exposure'], int)):
                if (self._bridge._configuration['thorcam']['exposure'] < self.exposure_range[0]) or (self._bridge._configuration['thorcam']['exposure'] > self.exposure_range[1]):
                    self._logger.error("Requested exposure range from configuration file is out of range {}:{}".format(self.exposure_range[0], self.exposure_range[1]))
                else:
                    self.set_setting("exposure_ms", self._bridge._configuration['thorcam']['exposure'])

            self.state = 3
            self._logger.debug(f"Supported trigger types: {self.supported_triggers}")
            return
        if msg == "settings":
            # We got the settings for this opened camera
            self._logger.debug("Camera settings")
            self._settings = value
            return
        if msg == "image":
            return
        self._logger.debug(f"Received unknown camera message {msg}: {value}")

    def got_image(self, image, count, queued_count, t):
        self._logger.debug("Received image (count: {}, queued count: {})".format(image, count, queued_count))
        self._write_image_to_file(image, f"c:\\temp\\image{count}.png")

    def _write_image_to_file(self, image, filename):
        data = image.to_bytearray()[0]
        image = Image.frombytes("I;16", image.get_size(), bytes(data))
        self._logger.info(f"Storing image {filename} to disk")
        image.save(filename)
        with open(filename+".bindump", "w") as f:
            f.write(str(bytes(data)))

    def setTrigger(self, hardware = False, frames = 1):
        if hardware and ("HW Trigger" not in self.supported_triggers):
            raise ValueError("Hardware trigger not supported")
        if not hardware and ("SW Trigger" not in self.supported_triggers):
            raise ValueError("Software trigger not supported")
        if frames < 0:
            raise ValueError("Triggering for a negative number of frames does not work")


        wasPlaying = self.cam_playing
        if wasPlaying:
            self._logger.debug("Stopping camera to change trigger setting")
            self.stop_playing_camera()
            while self.cam_playing:
                # Busy wait for stop ...
                time.sleep(0.1)

        self._logger.debug(f"Setting trigger mode to hardware={hardware}, triggering for {frames} frames")

        if hardware:
            self.set_setting("trigger_type", "HW Trigger")
        else:
            self.set_setting("trigger_type", "SW Trigger")
        self.set_setting("trigger_count", frames)

        if wasPlaying:
            self._logger.debug("Restarting camera after changing trigger setting")
            self.play_camera()


    def setExposure(self, exposureMillisecs):
        # Raise value error if we have an invalid exposure value
        exposureMillisecs = int(exposureMillisecs)
        if exposureMillisecs < 0:
            raise ValueError("Exposure duration has to be positive")
        if (exposureMillisecs < self.exposure_range[0]) or (exposureMillisecs > self.exposure_range[1]):
            raise ValueError(f"Exposure duration has to be in range [{self.exposure_range[0]}:{self.exposure_range[1]}]")

        wasPlaying = self.cam_playing
        if wasPlaying:
            self._logger.debug("Stopping camera to change exposure setting")
            self.stop_playing_camera()
            while self.cam_playing:
                # Busy wait for stop ...
                time.sleep(0.1)

        self.set_setting("exposure_ms", exposureMillisecs)

        if wasPlaying:
            self._logger.debug("Restarting camera after changing exposure setting")
            self.play_camera()


class ThorBridge:
    def __init__(
        self,

        logger = None,
        loglevel = logging.WARNING
    ):
        if logger is None:
            self._logger = logging.getLogger(__name__)
            # self._logger.basicConfig(format='%(levelname)s:%(message)s', level=loglevel)
            self._logger.addHandler(logging.StreamHandler())
        else:
            self._logger = logger

        self._terminate = False
        self._logger.setLevel(loglevel)
        self._configuration = None
        self._configuration_load_lasttry = None

        self._mqtt = None
        self._cam = None

        self._evtMainLoop = threading.Event()
        self._evtMQTTTerminated = threading.Event()

        self._mqttHandlers = None

    def _readConfigFile(self):
        cfgPath = os.path.join(Path.home(), ".config/thorbridge/bridge.conf")
        self._logger.debug(f"Trying to load configuration from {cfgPath}")
        cfgContent = None
        try:
            with open(cfgPath) as cfgFile:
                cfgContent = json.load(cfgFile)
        except FileNotFoundError:
            self._logger.warn(f"Failed to read configuration file from {cfgPath}")
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
                self._logger.warn("MQTT base topic not ending in trailing slash, appending")
                cfgContent['mqtt']['basetopic'] = cfgContent['mqtt']['basetopic'] + "/"


        # All checks passed - update configuration and raise event
        self._configuration = cfgContent
        self._logger.debug("Reloaded configuration file")

        # Update / set MQTT topics
        self._mqttHandlers = MQTTPatternMatcher()
        self._mqttHandlers.registerHandler(f"{self._configuration['mqtt']['basetopic']}trigger", [ self._mqtt_trigger ])

        return True

    def _mqtt_trigger(self, topic, msg):
        self._logger.debug("MQTT-REQ: Trigger")

    def main(self):
        while True:
            curTime = datetime.datetime.now(datetime.timezone.utc)

            # In case the re-read configuration even has been set shutdown everything
            # and drop our configuration, remaining part will be done by reinitialization
            # of all components as during startup

            ## ToDo

            # When we dropped our configuration we have to read it again ...
            if self._configuration is None:
                if (self._configuration_load_lasttry is None):
                    self._configuration_load_lasttry = curTime
                    if not self._readConfigFile():
                        # Since we have no configuration we just have to wait and re-read later on, we cannto continue service
                        time.sleep(15)
                    continue
                elif (curTime - self._configuration_load_lasttry).total_seconds() > 15:
                    self._configuration_load_lasttry = curTime
                    if not self._readConfigFile():
                        # Since we have no configuration we just have to wait and re-read later on, we cannto continue service
                        time.sleep(15)
                    continue

            # In case we have not initialized MQTT but have configuration we have to initialize
            # the MQTT client
            if (self._mqtt is None) and (self._configuration is not None):
                self._logger.debug("Re-initializing MQTT client")
                self._mqtt = mqtt.Client()
                self._mqtt.on_connect = self._mqtt_on_connect
                self._mqtt.on_message = self._mqtt_on_message
                self._mqtt.on_disconnect = self._mqtt_on_disconnect

                if (self._configuration['mqtt']['user'] is not None) and (self._configuration['mqtt']['password'] is not None):
                    self._mqtt.username_pw_set(self._configuration['mqtt']['user'], self._configuration['mqtt']['password'])
                self._mqtt.connect(self._configuration['mqtt']['broker'], self._configuration['mqtt']['port'])
                self._mqtt.loop_start()
                self._logger.debug("MQTT loop started")

            # In case we have not initialized the camera module up until now - do this now ...
            if (self._cam is None) and (self._configuration is not None):
                self._cam = ThorCamWrapper(bridge = self)

            # Wait for anything to do on the main thread (or the heartbeat)...
            if not self._evtMainLoop.is_set():
                self._evtMainLoop.wait(5)

            if self._cam is not None:
                self._cam.periodic()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._terminate = True

        if self._cam is not None:
            self._cam.shutdown()
            self._cam = None
        if self._mqtt is not None:
            self._mqtt.disconnect()
            while not self._evtMQTTTerminated.is_set():
                self._logger.debug("Waiting for MQTT event loop to terminate ...")
                self._evtMQTTTerminated.wait(5)
            self._mqtt = None

    def _mqtt_on_disconnect(self, client, userdata, rc):
        self._logger.debug("MQTT disconnected")
        if self._terminate:
            self._evtMQTTTerminated.set()

    def _mqtt_on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._logger.debug("Connected to MQTT server")

            # Subscribe to topics ...
            for topic in self._mqttHandlers._handlers:
                self._logger.debug(f"MQTT subscribing to {topic['pattern']}")
                client.subscribe(topic['pattern'])

            # ToDo: Publish retained messages about our status ...
        else:
            self._logger.warning(f"Failed to connect to MQTT server (code {rc})")

    def _mqtt_on_message(self, client, userdata, msg):
        pass











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
			if self._checkTopicMatch(basetopic + regHandler['pattern'], topic):
				if isinstance(regHandler['handler'], list):
					for handler in regHandler['handler']:
						handler(topic_stripped, message)
				elif callable(regHandler['handler']):
					regHandler['handler'](topic_stripped, message)



if __name__ == "__main__":
    with ThorBridge(loglevel = logging.DEBUG) as bridge:
        bridge.main()
