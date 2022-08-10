# QUAK/ESR ThorCam interface

__Note:__ Work in progress

This is a small Python service that runs on a Windows machine to which the
ThorCam is attached to provide a bridge into the control system that has
been realized on an OpenSource platform - it exposes an MQTT interface for
configuration of camera settings and queue configuration as well as event signalling
and allows to transfer images taken using SFTP.

Since the required .NET library to interface with the not so simple to handle
closed source ThorCam library this application only runs on Windows.

## Installation

```
pip install quakesrthorcam-tspspi
```

## Configuration file

### MQTT section

The MQTT section configures the ```broker```, ```port```, ```user```
and ```password``` of the MQTT broker. The ```basetopic``` is a topic string
that gets prepended to every message and to every subscription.

Currently this module subscribes to the following topics:

* ```trigger``` will allow software triggering of the camera (currently not implemented)
* ```setrun``` sets the current run parameters. Those are a current ```runprefix``` which
  is a single string that gets prepended in front of every filename and an optional
  list of strings called ```runsuffix```that are used instead of numbering the frames
  in consecutive order on each hardware trigger.
* ```exposure/set``` allows one to pass a message containing an ```exposure_ms``` field to
  update the exposure. The camera interrupts streaming and triggering operation during
  changes.

The camera publishes:

* ```raw/stored``` whenever a new raw frame has been stored and uploaded to
  the configured servers. It contains a ```localfilename``` and a ```imagefilename```.
  The local filename also includes the path on the camera server while the
  image filename is just the filename without any path by itself.

### Camera section ```thorcam```

* ```serial``` is able to specify the serial number of the camera that the service
  should bind to. In case no serial is specified the first available camera is used
* ```trigger``` is an dictionary that is able to configure the default trigger
  settings:
    * ```hardware``` can be ```true``` or ```false```
    * ```count``` specifies the number of frames to capture after the trigger has
      triggered the camera. This has to be either 0 for continuous capture or
      an positive integer.
* ```exposure``` can be used to set the default exposure (in milliseconds)

### Local file storage

* ```imagedir``` specifies the directory where images should be stored locally

### Upload configuration (SFTP)

* ```rawframesftp``` is a list of hosts to which the camera server should upload
  captured raw frames. Each entry is a dictionary that contains:
   * ```host``` specifies the host to which the upload should be made
   * ```user``` specifies the SSH user
   * ```destpath``` is the path on the remote machine where the images should be stored
   * ```keyfile``` points to the SSH private key file that should be used for authentication

## Example configuration file

```
{
	"mqtt" : {
		"broker" : "10.0.0.5",
		"port" : "1883",
		"user" : "YourMqttUser",

		"password" : "NONDISCLOSEDSECRETLONGSTRING",

		"basetopic" : "quakesr/experiment/camera/ebeam"


	},
	"thorcam" : {
		"trigger" : {
			"hardware" : true,
			"count" : 1
		},
		"exposure" : 80
	},
	"imagedir" : "c:\\temp\\",
	"rawframesftp" : [
		{
			"host" : "10.0.0.15",
			"user" : "camserv",
			"keyfile" : "c:\\users\\quak\\id_winselwolf",
			"destpath" : "/home/pi/measurements/data/images/"
		}
    ]
}
```

## Dependencies

* [paho-mqtt](https://www.eclipse.org/paho/) is the Eclipse Paho MQTT Python client
  that provides the interface to the MQTT broker (currently running on an [RabbitMQ](https://www.rabbitmq.com/)
  instance)
* [thorcam](https://pypi.org/project/thorcam/) is a wrapper around the .NET libraries
  supplied for the ThorCam service.
* [paramiko](https://www.paramiko.org) is a pure Python SSHv2 implementation mainly
  used for file transfer in this application.
* [Pillow](https://pypi.org/project/Pillow) is a python image library (PIL) clone
  that's used to encode the images.
