This package includes various useful metaclasses, classes and methods based on
the Inmarsat **FieldEdge** architecture using MQTT as an inter-service
communication (ISC) method.

## `Microservice` metaclass

### `tag`

Each microservice has a `tag` used as the first-layer subtopic when publishing
notifications to other microservices: `fieldedge/<tag>/...`, and for other
microservices to make requests: `fieldedge/<tag>/request/...`.

### `properties` and `isc_properties`

Each microservice has a `properties` attribute that provides a list of
exposed properties within the object, and `isc_properties` attribute that lists
properties exposed via ISC.  ISC properties may be optionally tagged at the
root level, and are automatically tagged for `Feature` and `MicroserviceProxy`
children of the Microservice.

Properties can be defined either as `__init__` attributes or using the
`@property` decorator.
Private properties (e.g. `_private`) are not exposed as `properties` nor
`isc_properties`.
Public properties documented within the class can be excluded from the exposed
list(s) by adding them to the private list(s) `self._hidden_properties` or
`self._hidden_isc_properties`.

Properties can also be categorized as either `info` (read-only) or `config`
(read/write) and reported via `properties_by_type` or `isc_properties_by_type`.
This is useful for reporting status and accepting configuration changes by
other microservices using MQTT.

### `_cached_properties`

A `PropertyCache` class is made available as a private method for caching
properties of the `Microservice` subclass.

### `rollcall_properties`

All microservices subscribe to topic `fieldedge/+/rollcall` that includes a
unique request identifier `uid` in the message. The microservice responds
with its own `fieldedge/<tag>/rollcall/response` with a message that includes
the request `uid` and a dictionary of the properties/values included in
`self._rollcall_properties`. Note that rollcall_properties is not included in
the list of `properties` or `isc_properties` (avoids circular reference).

Only ISC properties should be included in the rollcall properties list and
can be added or removed using the `rollcall_property_add()` or
`rollcall_property_remove()` methods.

### MQTT subscription message routing

The `Microservice` has a private method `_on_isc_message()` that is the first
layer of handling MQTT messages from the subscribed topic(s) that processes:

* `fieldedge/+/rollcall` with a `fieldedge/<tag>/rollcall/response`
* `fieldedge/<tag>/request/`...
    * `properties/list` responds with the list of all ISC properties
    * `properties/get` accepts a filter list and responds with a dictionary
    of { property: value }
    * `properties/set` requires a dictionary of { property: value } changes
    the properties and responds with a dictionary of changes.
    If the message includes key `reportChange` the message is also routed to
    the user `on_mqtt_message()` function.
    * Cycles through `self._features` passing to each `on_mqtt_message()` until
    `True` is returned indicating the feature handled the message.
    * Cycles through `self._ms_proxies` passing to each `_on_mqtt_message()`
    then `on_mqtt_message()` until `True` is returned indicating the proxy
    handled the message.

### `notify()`

The `self.notify()` method is used to publish MQTT messages. It formats them as
JSON-compatible and adds a `ts` unix timestamp field.

### Task queue

The `Microservice` includes a private `self._isc_queue`. If using this task
queue you should enable it with method `self.task_expiry_enable()`.
Tasks are added using either `self._isc_queue.add()` or `self.task_add()` and
retrieved using `self.task_get()`.

## `Feature` metaclass

`Feature`s are provided as a child component of a `Microservice` subclass.
They are initialized with a reference to the `_isc_queue` and callbacks to the
parent `notify()` and optional user-defined task completion or task failure
handlers.

### `properties_list()`

Feature properties that should be exposed to the parent's ISC properties
must be listed in the `properties_list()` abstractmethod return value.

### `status()`

The `status()` abstractmethod should return a dictionary of relevant
feature summary attributes or configurations.

### `on_isc_message()`

The `on_isc_message()` abstractmethod defines any MQTT topic handling,
effectively the API for other microservices to access methods of the Feature.
Each topic handled should return `True` with a default of `False` if no
topic is matched.

## `MicroserviceProxy` metaclass

The `MicroserviceProxy` is intended to represent a kind of digital twin of
another microservice and maintain cached property values of the other service
to reduce MQTT messaging for frequent property/value queries.

Similar to the Microservice, the proxy must be instantiated with a `tag` used
to establish MQTT pub/sub topics based on `fieldedge/<tag>/...`

The default property `cache_lifetime` for properties can be configured during
instantiation of the subclass.

It implements a single-depth blocking `IscTaskQueue` so that only one MQTT
request/response can be outstanding to a given other microservice.

### `initialize()`

Each proxy must use the `initialize()` method, which optionally triggers an
`init_callback` or `init_failure_callback`.

### `properties`

The proxy's `properties` query initiates an MQTT request to the other
microservice and blocks until the query returns or times out (default 10
seconds).

`property_get()` and `property_set()` methods perform those operations via
MQTT and cache updates.

### `task_add()` and `task_complete()`

These methods are used to put a MQTT query task in the queue, which blocks
until a response is received and processed based on a callback to the
`task.callback` or `task.task_meta['timeout_callback']` method.
`task_complete()` should be called by the callback to clear the queue for the
next task to be added.

### `publish()` and `subscribe()`

These methods allow the user to flexibly send MQTT queries and subscribe to
additional topics that will be handled by `on_isc_message()`.

### `on_isc_message()` abstractmethod

This method is required and must return `False` by default. It should return
`True` for any handled messages.
