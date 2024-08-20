# SolarMQTT

**SolarMQTT** is a Python script that simulates a photovoltaic (PV) system located in Venice, Italy, calculates the generated power using the `pvlib` library, and publishes the data to an MQTT broker. This project is ideal for IoT-based monitoring and analysis of solar energy production.

## Features

- **Photovoltaic System Simulation**: Computes solar power generation based on geographic location, weather conditions, and PV system parameters.
- **MQTT Communication**: Publishes the generated power to a specified MQTT topic for remote monitoring.
- **Real-Time Logging**: Provides detailed logs for monitoring the execution and status of the system.

## Prerequisites

Ensure the following Python libraries are installed:

```bash
pip install paho-mqtt pvlib pandas numpy
```

## Configuration

### MQTT Broker Settings

Configure the MQTT broker details in the script:

```python
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "SolarMQTT/impianto_test"
MQTT_LOG_TOPIC = "SolarMQTT/impianto_test/log"
MQTT_USER = "user"
MQTT_PASSWORD = "password"
```
Note: Replace these credentials and broker details with your own for production use.

### PV System Parameters

Adjust the PV system parameters according to your setup:

```python
module_parameters = {
    'pdc0': 220,  # Nominal DC power
    'gamma_pdc': -0.0047,  # Temperature coefficient of power
    't_noct': 47,  # Nominal operating cell temperature
}

inverter_parameters = {
    'pdc0': 250,  # Nominal DC power supported by the inverter
    'eta_inv_nom': 0.96,  # Nominal inverter efficiency
}

pv_system = pvlib.pvsystem.PVSystem(
    surface_tilt=30,
    surface_azimuth=180,
    module_parameters=module_parameters,
    inverter_parameters=inverter_parameters,
    racking_model='open_rack',
    module_type='glass_polymer',
)
```
### Logging
The script logs important events, such as MQTT connection status and generated power, to the console. Modify the logging configuration as needed:

```python
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
```
### License
This project is licensed under the MIT License - see the LICENSE file for details.

### Disclaimer
This script is provided "as-is" without any guarantees. Be sure to use secure credentials for MQTT and follow best practices for deploying IoT applications.
