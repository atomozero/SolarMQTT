import paho.mqtt.client as mqtt
import datetime
import pvlib
import logging
import time
import pandas as pd
import numpy as np
from tabulate import tabulate  # Importa tabulate

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

# Parametri del sistema fotovoltaico
module_parameters = {
    'pdc0': 220,
    'gamma_pdc': -0.0047,
    't_noct': 47,
}

inverter_parameters = {
    'pdc0': 250,
    'eta_inv_nom': 0.96,
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

# Creazione del client MQTT
client = mqtt.Client(protocol=mqtt.MQTTv311)
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

connected_flag = False

def on_connect(client, userdata, flags, rc):
    global connected_flag
    if rc == 0:
        logging.info("Connesso al broker MQTT")
        client.subscribe(MQTT_TOPIC)
        client.publish(MQTT_LOG_TOPIC, "Script connesso al server MQTT")
        connected_flag = True
    else:
        logging.error(f"Connessione fallita, codice di errore: {rc}")

client.on_connect = on_connect

# Connessione al broker
client.connect(MQTT_BROKER, MQTT_PORT)
client.loop_start()

# Attesa della connessione
while not connected_flag:
    logging.info("In attesa della connessione al broker MQTT...")
    time.sleep(1)

# Ciclo principale
try:
    while True:
        start_time = time.time()

        # Ottieni data e ora corrente
        now = pd.Timestamp(datetime.datetime.now(), tz='Europe/Rome')

        if now.hour < 6 or now.hour > 18:
            potenza_generata_kw = 0
        else:
            try:
                # Calcola posizione del sole
                solpos = pvlib.solarposition.get_solarposition(now, LATITUDE, LONGITUDE)
                logging.info(f"Solar Position:\n{tabulate(solpos, headers='keys', tablefmt='grid')}")

                dni_extra = pvlib.irradiance.get_extra_radiation(now)
                logging.info(f"DNI Extra: {dni_extra}")

                # Calcola l'irradiamento globale orizzontale (GHI), diretto normale (DNI), e diffuso orizzontale (DHI)
                ghi = dni_extra * np.cos(np.radians(solpos['apparent_zenith']))
                dhi = ghi * 0.1  # Assumiamo un valore per DHI (da migliorare)
                dni = dni_extra  # Assumiamo che DNI sia uguale a DNI extra (da migliorare)

                # Crea un DataFrame con i dati meteo
                weather_data = pd.DataFrame({
                    'ghi': [ghi.iloc[0]],  # Estrai il valore float con .iloc[0]
                    'dni': [dni],
                    'dhi': [dhi.iloc[0]]   # Estrai il valore float con .iloc[0]
                }, index=[now])

                logging.info(f"Weather Data:\n{tabulate(weather_data, headers='keys', tablefmt='grid')}")

                # Esegui il calcolo della potenza generata
                mc = pvlib.modelchain.ModelChain(pv_system, location, aoi_model='no_loss', spectral_model='no_loss', temperature_model='sapm')
                mc.run_model(weather=weather_data)

                # Stampa i risultati per debug
                #logging.info(f"ModelChain Results: {mc.results}")

                # Controllo e estrazione del valore DC
                if isinstance(mc.results.dc, pd.Series):
                    potenza_generata_kw = mc.results.dc.iloc[0] / 1000  # Utilizza il valore DC direttamente
                else:
                    logging.error("Risultato DC non trovato o non è una Series.")
                    potenza_generata_kw = 0

            except Exception as e:
                logging.error(f"Errore durante il calcolo dell'irraggiamento: {e}")
                potenza_generata_kw = 0

        # Pubblica i dati
        client.publish(MQTT_TOPIC, str(potenza_generata_kw))
        logging.info(f"Potenza generata: {potenza_generata_kw:.2f} kW inviata al topic {MQTT_TOPIC}")

        # Attesa per completare i 60 secondi
        time.sleep(max(0, 60 - (time.time() - start_time)))

except KeyboardInterrupt:
    logging.info("Script interrotto dall'utente.")

finally:
    client.loop_stop()
    client.disconnect()
