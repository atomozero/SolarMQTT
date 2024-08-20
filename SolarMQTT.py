import paho.mqtt.client as mqtt
import datetime
import pvlib
import logging
import time
import pandas as pd
import numpy as np

# Configurazione del logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Dettagli del broker MQTT
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "SolarMQTT/impianto_test"
MQTT_LOG_TOPIC = "SolarMQTT/impianto_test/log"
MQTT_USER = "user"
MQTT_PASSWORD = "password"

# Posizione geografica (Venezia)
LATITUDE, LONGITUDE = 45.44, 12.33

# Parametri del sistema fotovoltaico (espliciti)
module_parameters = {
    'pdc0': 220,  # Potenza nominale in DC
    'gamma_pdc': -0.0047,  # Coefficiente di temperatura della potenza
    't_noct': 47,  # Temperatura nominale di funzionamento della cella
}

inverter_parameters = {
    'pdc0': 250,  # Potenza nominale in DC supportata dall'inverter
    'eta_inv_nom': 0.96,  # Efficienza nominale dell'inverter
}

pv_system = pvlib.pvsystem.PVSystem(
    surface_tilt=30,
    surface_azimuth=180,
    module_parameters=module_parameters,
    inverter_parameters=inverter_parameters,
    racking_model='open_rack',  
    module_type='glass_polymer',
)
location = pvlib.location.Location(LATITUDE, LONGITUDE, tz='Europe/Rome')

# Creazione del client MQTT (corretto per il deprecation warning)
client = mqtt.Client(protocol=mqtt.MQTTv311)  # Specifica il protocollo MQTTv311
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Connesso al broker MQTT")
        client.subscribe(MQTT_TOPIC)
        client.publish(MQTT_LOG_TOPIC, "Script connesso al server MQTT")
    else:
        logging.error(f"Connessione fallita, codice di errore: {rc}")

client.on_connect = on_connect

# Connessione al broker
client.connect(MQTT_BROKER, MQTT_PORT)
client.loop_start()

# Attesa della connessione
while not client.is_connected():
    logging.info("In attesa della connessione al broker MQTT...")
    time.sleep(1)

# Ciclo principale
try:
    while True:
        start_time = time.time()

        # Ottieni data e ora corrente
        now = pd.Timestamp(datetime.datetime.now(), tz='Europe/Rome')

        # Check if it's nighttime
        if now.hour < 6 or now.hour > 18:  # Adjust these hours based on your location and definition of nighttime
            potenza_generata_kw = 0
        else:
            # Calcola posizione del sole a mezzogiorno per ottenere l'ora del solar noon
            solar_noon_position = pvlib.solarposition.get_solarposition(
                pd.Timestamp(now.date(), tz='Europe/Rome') + pd.Timedelta(hours=12), 
                LATITUDE,
                LONGITUDE
            )
            solar_noon = solar_noon_position.index[0]

            # Calcola posizione del sole, ecc.
            solpos = pvlib.solarposition.get_solarposition(now, LATITUDE, LONGITUDE)
            dni_extra = pvlib.irradiance.get_extra_radiation(now)
            I0h = pvlib.irradiance.get_extra_radiation(solar_noon)

            # Handle cases where kt is None or zero
            if I0h == 0 or dni_extra == 0:
                kt = 0
            else:
                kt = dni_extra / I0h

            # Calcola l'irraggiamento, handling cases where kt is zero
            ghi = pd.Series(kt * I0h if kt else 0, index=[now])
            dhi = pd.Series((kt * I0h) - dni_extra * pvlib.tools.cosd(solpos['apparent_zenith']) if kt else 0, index=[now])
            poa_irradiance = pvlib.irradiance.get_total_irradiance(
                surface_tilt=30,
                surface_azimuth=180,
                solar_zenith=solpos['apparent_zenith'],
                solar_azimuth=solpos['azimuth'],
                dni=dni_extra,
                ghi=ghi,
                dhi=dhi,
                airmass=pvlib.atmosphere.get_relative_airmass(solpos['apparent_zenith']),
                albedo=0.2
            )

            # Calcola GHI direttamente da POA irradiance components
            ghi = pvlib.irradiance.get_total_irradiance(
                surface_tilt=0,
                surface_azimuth=180,
                solar_zenith=solpos['apparent_zenith'],
                solar_azimuth=solpos['azimuth'],
                dni=poa_irradiance['poa_direct'] / pvlib.tools.cosd(solpos['apparent_zenith']),
                ghi=None,
                dhi=poa_irradiance['poa_diffuse'],
                airmass=pvlib.atmosphere.get_relative_airmass(solpos['apparent_zenith']),
                albedo=0.2
            )['ghi']

            dni = poa_irradiance['poa_direct'] / pvlib.tools.cosd(solpos['apparent_zenith'])
            dhi = ghi - dni

            # Create a DataFrame with the calculated GHI, DNI, and DHI
            weather = pd.DataFrame({'ghi': ghi, 'dni': dni, 'dhi': dhi}, index=[now])

            # Crea il ModelChain specificando il modello di temperatura
            mc = pvlib.modelchain.ModelChain(pv_system, location, aoi_model='no_loss', spectral_model='no_loss', temperature_model='sapm')
            mc.run_model(weather=weather)

            # Calcola la potenza generata
            mc.results.dc = mc.results.dc.reset_index(drop=True)
            potenza_generata_kw = mc.results.dc['p_mp'].values[0] / 1000

        # Pubblica i dati
        client.publish(MQTT_TOPIC, str(potenza_generata_kw))
        print(f"Potenza generata: {potenza_generata_kw:.2f} kW inviata al topic {MQTT_TOPIC}")

        # Attesa per completare i 60 secondi
        time.sleep(max(0, 60 - (time.time() - start_time)))

except KeyboardInterrupt:
    logging.info("Script interrotto dall'utente.")

finally:
    # Disconnessione
    client.loop_stop()
    client.disconnect()
