import paho.mqtt.client as mqtt
import json
import time
import threading # For running the MQTT loop in a separate thread
import random    # For generating a unique client ID

class MQTTClient:
    def __init__(self, broker_ip: str, port: int, pi_id: str, message_callback):
        """
        Initializes the MQTT client.

        Args:
            broker_ip (str): The IP address of the Mosquitto broker.
            port (int): The port of the Mosquitto broker (usually 1883).
            pi_id (str): A unique ID for this Raspberry Pi (e.g., "pi1", "pi2").
            message_callback (callable): A function in the main application
                                         to call when a new chat message is received.
        """
        self.broker_ip = broker_ip
        self.port = port
        self.pi_id = pi_id
        self.message_callback = message_callback # This will be a method in your main app

        # Generate a unique client ID. MQTT client IDs must be unique per broker.
        self.client_id = f"pi_chatbot_{self.pi_id}_{random.randint(1000, 9999)}"

        # Create a new MQTT client instance
        # Using CallbackAPIVersion.VERSION2 for newer paho-mqtt versions (2.0.0+)
        self.client = mqtt.Client(
            client_id=self.client_id,
            protocol=mqtt.MQTTv311, # Or mqtt.MQTTv5 if your broker supports and you want to use MQTTv5 features
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )

        # Assign callback functions
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        # Topics this Pi will subscribe to:
        self.inbox_topic = f"pi/chat/inbox/{self.pi_id}"
        self.status_topic_prefix = "pi/status/"
        self.status_own_topic = f"{self.status_topic_prefix}{self.pi_id}/online"
        self.chat_topic_prefix = "pi/chat/outbox/" # For publishing to other Pi's inbox
        self.topic_broadcast_prefix = "pi/chat/topic/" # For broadcasting current chat topic

        self.other_pis_online = {} # To keep track of other PIs' online status

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback for when the client connects to the MQTT broker."""
        if reason_code == 0:
            print(f"MQTT Client {self.client_id} Connected successfully to broker {self.broker_ip}")
            # Subscribe to topics when connected
            self.client.subscribe(self.inbox_topic, qos=1) # QoS 1 for reliable message delivery
            self.client.subscribe(f"{self.status_topic_prefix}+/online", qos=0) # QoS 0 for status (less critical)
            self.client.subscribe(f"{self.topic_broadcast_prefix}+", qos=0) # Subscribe to all topic broadcasts
            print(f"Subscribed to: {self.inbox_topic}")
            print(f"Subscribed to: {self.status_topic_prefix}+/online")
            print(f"Subscribed to: {self.topic_broadcast_prefix}+")
        else:
            print(f"Failed to connect, return code {reason_code}")

    def _on_message(self, client, userdata, msg):
        """Callback for when a PUBLISH message is received from the broker."""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')

        print(f"MQTT Received: Topic='{topic}' Message='{payload}'")

        # Handle status messages
        if topic.startswith(self.status_topic_prefix) and topic.endswith("/online"):
            other_pi_id = topic.split('/')[2] # Extract pi_id from topic like "pi/status/pi1/online"
            self.other_pis_online[other_pi_id] = (time.time(), payload == "online")
            print(f"Status update: {other_pi_id} is {'online' if payload == 'online' else 'offline'}")
            return # Don't pass status messages to the chat callback

        # Handle chat topic broadcasts (e.g., to keep context of conversation if initiating chat)
        if topic.startswith(self.topic_broadcast_prefix):
            other_pi_id = topic.split('/')[3]
            # You might want to store this in your main application's state
            # For now, we'll just print it.
            print(f"Topic broadcast from {other_pi_id}: {payload}")
            return # Don't pass topic broadcasts to the chat callback directly

        # If it's a chat inbox message, pass it to the main application's callback
        if topic == self.inbox_topic:
            try:
                # Assuming chat messages are simple strings for now.
                # You might want to use JSON for more complex message structures.
                self.message_callback(payload)
            except Exception as e:
                print(f"Error processing received message: {e}")

    def _on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects from the broker."""
        print(f"MQTT Client {self.client_id} Disconnected with result code: {rc}")
        # Paho-mqtt has automatic re-connection built-in by default for loop_start/loop_forever

    def connect(self):
        """Starts the MQTT client connection in a background thread."""
        try:
            self.client.connect(self.broker_ip, self.port, keepalive=60)
            self.client.loop_start() # Start a background thread for network traffic
            print(f"Attempting to connect to MQTT broker at {self.broker_ip}:{self.port}")
        except Exception as e:
            print(f"Failed to initiate MQTT connection: {e}")

    def disconnect(self):
        """Stops the MQTT client background thread and disconnects."""
        self.client.loop_stop() # Stop the background thread
        self.client.disconnect()
        print(f"MQTT Client {self.client_id} disconnected.")

    def publish_chat_message(self, target_pi_id: str, message: str):
        """Publishes a chat message to another Raspberry Pi's inbox."""
        topic = f"pi/chat/inbox/{target_pi_id}" # Publish to the other Pi's inbox
        print(f"MQTT Publishing to {topic}: {message}")
        self.client.publish(topic, message, qos=1) # QoS 1 for reliable chat messages

    def publish_status(self, is_online: bool):
        """Publishes this Pi's online/offline status."""
        payload = "online" if is_online else "offline"
        self.client.publish(self.status_own_topic, payload, qos=0, retain=True) # Retain for last known status
        print(f"MQTT Publishing status: {self.pi_id} is {payload}")

    def publish_current_chat_topic(self, topic: str):
        """Publishes the current chat topic for context to other PIs."""
        full_topic = f"{self.topic_broadcast_prefix}{self.pi_id}"
        self.client.publish(full_topic, topic, qos=0, retain=True)
        print(f"MQTT Publishing chat topic: {topic}")


    def is_other_pi_online(self, other_pi_id: str, max_age_seconds: int = 120) -> bool:
        """
        Checks if a specific other Pi is considered online based on recent heartbeats.
        """
        if other_pi_id == self.pi_id: # A Pi is always online to itself
            return True

        if other_pi_id in self.other_pis_online:
            last_seen_time, status = self.other_pis_online[other_pi_id]
            # Consider online if last status was online and within max_age_seconds
            if status and (time.time() - last_seen_time) < max_age_seconds:
                return True
        return False

# --- Example Usage (for testing this module independently) ---
if __name__ == "__main__":
    # --- Configuration for testing ---
    # IMPORTANT: Replace with YOUR broker's IP address
    # You need two terminals, acting as 'pi1' and 'pi2'
    # In one terminal, run: python mqtt_client.py pi1 <BROKER_IP>
    # In the other terminal, run: python mqtt_client.py pi2 <BROKER_IP>
    # Watch the output in both. Then try publishing a message.
    
    # Simple message callback for testing
    def test_message_received(message):
        print(f"\n[MAIN APP] Received Chat Message: {message}\n")

    import sys
    if len(sys.argv) < 3:
        print("Usage: python mqtt_client.py <pi_id> <broker_ip>")
        sys.exit(1)

    my_pi_id = sys.argv[1]
    broker_ip_arg = sys.argv[2]
    
    mqtt_port = 1883 # Default MQTT port

    print(f"--- Starting MQTT Client for {my_pi_id} ---")
    mqtt_manager = MQTTClient(
        broker_ip=broker_ip_arg,
        port=mqtt_port,
        pi_id=my_pi_id,
        message_callback=test_message_received
    )
    mqtt_manager.connect()

    # Keep publishing status and check other Pi's status
    try:
        while True:
            mqtt_manager.publish_status(is_online=True)
            # Find the ID of the other Pi
            other_pi_id = "pi1" if my_pi_id == "pi2" else "pi2"
            
            # Check if the other Pi is online
            if mqtt_manager.is_other_pi_online(other_pi_id):
                print(f"{other_pi_id} is online.")
                # Example: If pi1, send a message to pi2 after 10 seconds
                if my_pi_id == "pi1" and random.random() < 0.2: # Randomly send
                     msg = f"Hello from {my_pi_id}! Current time is {time.strftime('%H:%M:%S')}."
                     mqtt_manager.publish_chat_message(other_pi_id, msg)
                # Example: If pi2, broadcast a random topic
                if my_pi_id == "pi2" and random.random() < 0.1:
                    topics = ["AI ethics", "quantum computing", "robot rights", "future of food"]
                    mqtt_manager.publish_current_chat_topic(random.choice(topics))
            else:
                print(f"{other_pi_id} is offline or hasn't checked in recently.")

            time.sleep(5) # Publish status every 5 seconds

    except KeyboardInterrupt:
        print("\nDisconnecting MQTT client...")
        mqtt_manager.publish_status(is_online=False) # Publish offline status
        mqtt_manager.disconnect()
        print("MQTT client disconnected.")