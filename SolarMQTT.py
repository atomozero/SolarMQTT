import paho.mqtt.client as mqtt
import datetime
import pvlib
import logging
import time
import pandas as pd
import numpy as np
from tabulate import tabulate
import json  # Importa json

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
    'pdc0': 200,  # Potenza di picco del modulo (W)
    'gamma_pdc': -0.0047,  # Coefficiente di temperatura della potenza (%/°C)
    't_noct': 47,  # Temperatura nominale di esercizio della cella (°C)
}

inverter_parameters = {
    'pdc0': 1000,  # Potenza di picco dell'inverter (W)
    'eta_inv_nom': 0.96,  # Efficienza nominale dell'inverter
}

pv_system = pvlib.pvsystem.PVSystem(
    surface_tilt=30,
    surface_azimuth=180,
    module_parameters=module_parameters,
    inverter_parameters=inverter_parameters,
    modules_per_string=5,  # Numero di moduli per stringa
    strings_per_inverter=1,  # Numero di stringhe per inverter
    racking_model='open_rack',
    module_type='glass_polymer',
)

location = pvlib.location.Location(LATITUDE, LONGITUDE, tz='Europe/Rome')

# Creazione del client MQTT
client = mqtt.Client()
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

def on_disconnect(client, userdata, rc):
    global connected_flag
    logging.info("Disconnesso dal broker MQTT")
    client.publish(MQTT_LOG_TOPIC, "Script disconnesso dal server MQTT")
    connected_flag = False

client.on_disconnect = on_disconnect

# Connessione al broker
client.connect(MQTT_BROKER, MQTT_PORT)
client.loop_start()

# Attesa della connessione
while not connected_flag:
    logging.info("In attesa della connessione al broker MQTT...")
    time.sleep(1)

# Variabile per accumulare l'energia generata
energia_totale_kwh = 0

# Ciclo principale
try:
    while True:
        start_time = time.time()

        # Ottieni data e ora corrente
        now = pd.Timestamp(datetime.datetime.now(), tz='Europe/Rome')

        # Considera l'orario estivo per la generazione di energia
        if now.month in [6, 7, 8] and (now.hour < 6 or now.hour > 20):
            potenza_generata_w = 0
        elif now.hour < 6 or now.hour > 18:
            potenza_generata_w = 0
        else:
            try:
                # Calcola posizione del sole
                solpos = pvlib.solarposition.get_solarposition(now, LATITUDE, LONGITUDE)
                logging.info(f"Solar Position:\n{tabulate(solpos, headers='keys', tablefmt='grid')}")

                dni_extra = pvlib.irradiance.get_extra_radiation(now)  # DNI Extra: Irradiazione solare diretta al di fuori dell'atmosfera
                logging.info(f"DNI Extra: {dni_extra}")

                # Calcola l'irradiamento globale orizzontale (GHI), diretto normale (DNI), e diffuso orizzontale (DHI)
                ghi = dni_extra * np.cos(np.radians(solpos['apparent_zenith']))  # GHI: Irradiazione globale orizzontale
                dhi = ghi * 0.1  # DHI: Irradiazione diffusa orizzontale (assunto)
                dni = dni_extra  # DNI: Irradiazione diretta normale (assunto)

                # Crea un DataFrame con i dati meteo
                weather_data = pd.DataFrame({
                    'ghi': [ghi.iloc[0]],  # Estrai il valore float con .iloc[0]
                    'dni': [dni],
                    'dhi': [dhi.iloc[0]]   # Estrai il valore float con .iloc[0]
                }, index=[now])

                # Esegui il calcolo della potenza generata
                mc = pvlib.modelchain.ModelChain(pv_system, location, aoi_model='no_loss', spectral_model='no_loss', temperature_model='sapm')
                mc.run_model(weather=weather_data)

                # Controllo e estrazione del valore DC
                if isinstance(mc.results.dc, pd.Series):
                    potenza_generata_w = mc.results.dc.iloc[0]  # Utilizza il valore DC direttamente
                else:
                    logging.error("Risultato DC non trovato o non è una Series.")
                    potenza_generata_w = 0

                # Potenza effettivamente generata dai pannelli
                potenza_generata_effettiva_w = potenza_generata_w

                # Controllo e limitazione della potenza generata
                potenza_generata_w = min(potenza_generata_w, inverter_parameters['pdc0'])

                # Potenza filtrata dall'inverter per via del suo rendimento
                potenza_filtrata_inverter_w = potenza_generata_w * inverter_parameters['eta_inv_nom']

                # Calcola la temperatura del modulo
                temperature = mc.results.cell_temperature.iloc[0]
                logging.info(f"Temperatura calcolata: {temperature:.2f} °C")

                # Log delle potenze
                logging.info(f"Potenza effettivamente generata dai pannelli (corretta per temperatura): {potenza_generata_effettiva_w:.2f} W")
                logging.info(f"Potenza filtrata dall'inverter: {potenza_filtrata_inverter_w:.2f} W")

            except Exception as e:
                logging.error(f"Errore durante il calcolo dell'irraggiamento: {e}")
                potenza_generata_w = 0

        # Converti la potenza in kilowatt per il topic MQTT
        potenza_generata_kw = potenza_filtrata_inverter_w / 1000

        # Calcola l'energia generata in questo ciclo (in kWh)
        energia_generata_kwh = potenza_generata_kw * (60 / 3600)  # 60 secondi = 1 minuto

        # Aggiungi l'energia generata al totale
        energia_totale_kwh += energia_generata_kwh

        # Crea il payload JSON
        payload = {
            'timestamp': now.isoformat(),
            'potenza_generata_kw': potenza_generata_kw,
            'energia_totale_kwh': energia_totale_kwh,
            'solar_position': solpos.to_dict(orient='records')[0],
            'weather_data': weather_data.to_dict(orient='records')[0],
            'temperature': temperature  # Aggiungi la temperatura al payload
        }

        # Pubblica i dati in formato JSON
        client.publish(MQTT_TOPIC, json.dumps(payload))
        logging.info(f"Potenza generata: {potenza_generata_kw:.2f} kW inviata al topic {MQTT_TOPIC}")
        logging.info(f"Energia totale generata: {energia_totale_kwh:.2f} kWh")

        # Attesa per completare i 60 secondi
        time.sleep(max(0, 60 - (time.time() - start_time)))

except KeyboardInterrupt:
    logging.info("Script interrotto dall'utente.")
    client.publish(MQTT_LOG_TOPIC, "Script interrotto dall'utente.")

finally:
    client.loop_stop()
    client.disconnect()
    client.publish(MQTT_LOG_TOPIC, "Script disconnesso dal server MQTT")
