import asyncio
from mcp.server.fastmcp import FastMCP
from typing import Literal
import time
import sys # For parsing args in __main__ for mcp dev

# --- Mock objects for independent testing (remain the same) ---
class MockDisplayManager:
    def display_message(self, message, *args, **kwargs):
        print(f"[Mock Display] {message}")
    def display_screensaver_text(self, text):
        print(f"[Mock Display Screensaver] {text}")
    def update_display(self): pass
    def quit(self): pass

class MockMQTTClient:
    def __init__(self):
        self.messages_sent = []
        self.online_status = {"pi1": (time.time(), True), "pi2": (time.time(), True)}
    def publish_chat_message(self, target_pi_id, message):
        self.messages_sent.append({"target": target_pi_id, "message": message})
        print(f"[Mock MQTT] Published to {target_pi_id}: {message}")
    def publish_status(self, is_online):
        print(f"[Mock MQTT] My status: {'online' if is_online else 'offline'}")
    def publish_current_chat_topic(self, topic):
        print(f"[Mock MQTT] Broadcasted topic: {topic}")
    def is_other_pi_online(self, other_pi_id: str) -> bool:
        return self.online_status.get(other_pi_id, (0, False))[1]

# --- Global FastMCP instance definition (adjusted) ---
# This part handles how 'mcp dev' finds the server.
# The 'mcp' object is created here and will be passed into MCPServerManager.
# We determine the pi_id for naming before creating the global 'mcp' object.
_default_pi_id_for_global_mcp = "pi1"
_temp_pi_id_for_global_mcp = _default_pi_id_for_global_mcp

# Parse arguments ONLY if this script is being run directly.
# mcp dev typically passes the args after the script.
if __name__ == "__main__":
    if len(sys.argv) > 1:
        _temp_pi_id_for_global_mcp = sys.argv[1]

# Define the global 'mcp' instance here.
# This instance will be decorated with tools.
mcp = FastMCP(
    name=f"pi-chatbot-{_temp_pi_id_for_global_mcp}-server",
    instructions=(
        f"This server controls Raspberry Pi {_temp_pi_id_for_global_mcp}. "
        "It can display messages on its HDMI screen and send messages to another Pi "
        "via MQTT. It can also provide status about its operational mode and the "
        "current conversation topic."
    )
)

class MCPServerManager:
    def __init__(self, pi_id: str, display_manager, mqtt_client):
        """
        Initializes the MCP server for this Raspberry Pi.

        Args:
            pi_id (str): The unique ID of this Pi (e.g., "pi1", "pi2").
            display_manager (DisplayManager): An instance of your DisplayManager.
            mqtt_client (MQTTClient): An instance of your MQTTClient.
        """
        self.pi_id = pi_id
        self.display_manager = display_manager
        self.mqtt_client = mqtt_client
        
        # --- CRITICAL FIX: Store the global 'mcp' instance as an attribute ---
        self.mcp = mcp
        # --- END CRITICAL FIX ---

        # Register tools with this specific manager's context (real display/mqtt clients)
        # Note: The @mcp.tool decorator already registers with the global `mcp` instance.
        # This call primarily sets up the closures for the tools with the correct
        # display_manager and mqtt_client instances that are passed to this constructor.
        self._register_tools(self.pi_id, self.display_manager, self.mqtt_client)
        print(f"MCP Server for Pi '{self.pi_id}' (managed by MCPServerManager) initialized with tools.")

    def _register_tools(self, pi_id, display_manager, mqtt_client):
        """Registers all the tools that the LLM can call using the global 'mcp' instance."""
        # The @mcp.tool decorators below register tools to the global `mcp` instance.
        # The inner functions close over the pi_id, display_manager, and mqtt_client
        # provided at the time MCPServerManager is instantiated.

        @mcp.tool()
        async def display_message(message: str) -> str:
            """
            Displays a text message on this Raspberry Pi's HDMI screen.

            Args:
                message (str): The text message to display.
            Returns:
                str: A confirmation message.
            """
            print(f"[MCP Tool ({pi_id})] Displaying message: {message[:50]}...")
            display_manager.display_message(message)
            return "Message displayed successfully."

        @mcp.tool()
        async def send_chat_message_to_other_pi(
            target_pi_id: Literal["pi1", "pi2"],
            message: str
        ) -> str:
            """
            Sends a chat message to the other Raspberry Pi via MQTT.
            The message will be processed by the other Pi's AI.

            Args:
                target_pi_id (Literal["pi1", "pi2"]): The ID of the target Raspberry Pi.
                                                        Must be "pi1" or "pi2".
                message (str): The chat message to send.
            Returns:
                str: A confirmation message indicating if the message was sent.
            """
            if target_pi_id == pi_id:
                return f"Error: Cannot send message to self ({pi_id})."
            
            print(f"[MCP Tool ({pi_id})] Sending message to {target_pi_id}: {message[:50]}...")
            mqtt_client.publish_chat_message(target_pi_id, message)
            return f"Message sent to {target_pi_id}."

        @mcp.tool()
        async def get_pi_status(query_pi_id: Literal["self", "other"]) -> dict:
            """
            Retrieves the current status of this Pi or the other Pi.

            Args:
                query_pi_id (Literal["self", "other"]): Whether to get status for 'self' or the 'other' Pi.
            Returns:
                dict: A dictionary containing status information (e.g., {"mode": "idle", "online": true}).
                      For 'other', it will indicate if the other Pi is detected as online.
            """
            status = {"pi_id": pi_id}
            # These will need to be populated by the main application's current state
            status['mode'] = "unknown" # Placeholder
            status['online'] = True # Placeholder (this pi is always online if server is running)

            if query_pi_id == "other":
                other_id = "pi1" if pi_id == "pi2" else "pi2"
                status['other_pi_id'] = other_id
                status['other_pi_online'] = mqtt_client.is_other_pi_online(other_id)
            else:
                status['current_chat_topic'] = "unknown" # Placeholder for now

            print(f"[MCP Tool ({pi_id})] Getting status for {query_pi_id}: {status}")
            return status

        @mcp.tool()
        async def broadcast_chat_topic(topic: str) -> str:
            """
            Broadcasts the current conversation topic to all connected Raspberry Pis.
            This helps align context across devices.

            Args:
                topic (str): The current topic of discussion.
            Returns:
                str: A confirmation message.
            """
            print(f"[MCP Tool ({pi_id})] Broadcasting topic: {topic}")
            mqtt_client.publish_current_chat_topic(topic)
            return "Chat topic broadcasted."

    def run_server(self):
        """
        Runs the MCP server using the stdio transport.
        Note: This blocks. In main.py, you'd typically run this in a separate thread/task.
        """
        print(f"Starting MCP server '{self.mcp.name}' with stdio transport...")
        self.mcp.run(transport='stdio')
        print(f"MCP server '{self.mcp.name}' stopped.")

# --- Handling for `mcp dev` and direct execution (remains the same) ---
# This block ensures the global 'mcp' instance is created correctly
# when the file is imported by `mcp dev` or run directly.
# The _mcp_instance_for_dev_test is created just to ensure tools are registered.
_mcp_instance_for_dev_test = MCPServerManager(
    pi_id=_temp_pi_id_for_global_mcp,
    display_manager=_mock_display,
    mqtt_client=_mock_mqtt
)

print("\n--- MCP Server Ready for Connections (for 'mcp dev' testing) ---")
print(f"To test, run in a separate terminal (with venv active, in project root):")
print(f"  mcp dev src/mcp_server.py:mcp --args {_temp_pi_id_for_global_mcp}")
print("   (Replace 'pi1' or 'pi2' if you are trying different IDs.)")
print("Or configure Claude Desktop to connect to this server.")
print("Press Ctrl+C to stop this terminal if you ran it via python directly.")