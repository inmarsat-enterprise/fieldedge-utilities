# Inmarsat FieldEdge Utilities

Inmarsat FieldEdge project supports *Internet of Things* (**IoT**) using
satellite communications technology.

This library available on **PyPI** provides:

* A common **`logger`** format and wrapping file facility.
* A repeating **`timer`** utility (thread) that can be started, stopped,
restarted, and interval changed.
* A simplified **`mqtt`** client that automatically (re)onnects
(by default to a local `fieldedge-broker`).
* Helper functions for managing files and **`path`** on different OS.
* An interface for the FieldEdge **`hostpipe`** service for sending host
commands from a Docker container, with request/result captured in a logfile.
* Helper functions **`ip_interfaces`** for finding and validating IP interfaces
and addresses/subnets.
* A defined set of common **`ip_protocols`** used for packet analysis and
satellite data traffic optimisation.
* Helpers for **`class_properties`** to expose public properties of classes
for MQTT transport between microservices, converting between PEP and JSON style.
(replaced by `microservice.properties`)
* Helpers for managing **`serial`** ports on a host system.
* Utilities for converting **`timestamp`**s between unix and ISO 8601
* Classes useful for implementing **`microservice`**s based on MQTT
inter-service communications and task workflows:
    * **`properties`** manipulation and conversion between JSON and PEP style,
    and derived from classes or instances.
    * **`interservice`** communications tasks and searchable queue.
    * **`propertycache`** concept for caching frequently referenced object
    properties where the query may take time.
    * **`microservice`** classes for abstraction and proxy operations

[Docmentation](https://inmarsat-enterprise.github.io/fieldedge-utilities/)
