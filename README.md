# Inmarsat FieldEdge Utilities

Inmarsat FieldEdge project supports *Internet of Things* (**IoT**) using
satellite communications technology.

This library available on **PyPI** provides:

* A common **`logger`** format and wrapping file facility.
* A repeating **`timer`** utility (thread) that can be started, stopped,
restarted, and interval changed.
* A simplified **`mqtt`** client that automatically connects
(by default to a local `fieldedge-broker`).
* Helper functions for managing files and **`path`** on different OS.
* An interface for the FieldEdge **`hostpipe`** service for sending host
commands from a Docker container, with request/result captured in a logfile.
* Helper functions **`ip_interfaces`** for finding and validating IP interfaces
and addresses/subnets.
* A defined set of common **`protocols`** used for packet analysis and
satellite data traffic optimisation.
* Helpers for **`tag`** assignment of class definitions to expose properties
for MQTT transport between microservices, converting between PEP and JSON style.
* Helpers for managing **`serial`** ports on a host system.
* Utilities for converting **`timestamp`**s between unix and ISO 8601

[Docmentation](https://inmarsat-enterprise.github.io/fieldedge-utilities/)
