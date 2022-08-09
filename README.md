# QUAK/ESR ThorCam interface

__Note:__ Work in progress, SCP interface currently not working

This is a small Python service that runs on a Windows machine to which the
ThorCam is attached to provide a bridge into the control system that has
been realized on an OpenSource platform - it exposes an MQTT interface for
configuration of camera settings and queue configuration as well as event signalling
and allows to transfer images taken using SCP.

Since the required .NET library to interface with the not so simple to handle
closed source ThorCam library this application only runs on Windows.

## Installation

```
pip install quakesrthorcam-tspspi
```

## Configuration file

### MQTT section

### Camera section

* ```serial``` is able to specify the serial number of the camera that the service
  should bind to
* ```trigger``` is an dictionary that is able to configure the default trigger
  settings:
    * ```hardware``` can be ```true``` or ```false```
    * ```count``` specifies the number of frames to capture after the trigger has
      triggered the camera. This has to be either 0 for continuous capture or
      an positive integer.

## Dependencies

* [paho-mqtt](https://www.eclipse.org/paho/) is the Eclipse Paho MQTT Python client
  that provides the interface to the MQTT broker (currently running on an [RabbitMQ](https://www.rabbitmq.com/)
  instance)
* [thorcam](https://pypi.org/project/thorcam/) is a wrapper around the .NET libraries
  supplied for the ThorCam service.
