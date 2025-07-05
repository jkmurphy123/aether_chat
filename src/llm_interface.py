import os
from dotenv import load_dotenv
import asyncio

# --- Google Generative AI Python SDK Imports ---
from google import genai
from google.genai.types import (
    GenerateContentConfig, # We will use this now
    FunctionCallingConfig, # This will go inside GenerateContentConfig
    HarmCategory,
    HarmBlockThreshold,
    Content, # For constructing explicit Content objects
    Part     # For constructing explicit Part objects
)

# --- Load environment variables ---
load_dotenv()

class GeminiLLMInterface:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables. Please set it in your .env file.")

        self.client = genai.Client(api_key=api_key)
        self.model_name = 'gemini-2.0-flash-001' # Or 'gemini-1.5-flash' or 'gemini-2.0-flash-001'

    async def generate_response_with_tools(self, messages_history: list, tools: list):
        """
        Generates a response from the Gemini model, optionally using provided tools.

        Args:
            messages_history (list): A list of messages for the chat history, in Gemini API format.
            tools (list): A flat list of FunctionDeclaration dictionaries.
                          Example: [{"name": "tool_name", "description": "...", "parameters": {...}}]
        Returns:
            google.generativeai.types.Content: The content object from the model's response.
        """
        try:
            # --- CRITICAL FIX: Re-introduce GenerateContentConfig and pass all relevant params to it ---
            # The 'tools' parameter in GenerateContentConfig expects a FLAT LIST of FunctionDeclaration dictionaries.
            # This is the most important part we've been debugging.
            
            config_obj = GenerateContentConfig(
                tools=tools, # Pass the flat list of FunctionDeclaration dictionaries directly here
                tool_config=FunctionCallingConfig(mode="AUTO"), # Pass FunctionCallingConfig object
                # Other generation parameters can go here (e.g., temperature, max_output_tokens)
            )
            
            safety_settings_list = [
                {"category": HarmCategory.HAR_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_ONLY_HIGH},
                {"category": HarmCategory.HAR_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_ONLY_HIGH},
                {"category": HarmCategory.HAR_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_ONLY_HIGH},
                {"category": HarmCategory.HAR_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_ONLY_HIGH},
            ]

            # Now call generate_content with 'config' and 'safety_settings' as top-level arguments
            response = await self.client.models.generate_content(
                model=self.model_name,
                contents=messages_history,
                config=config_obj, # Pass the GenerateContentConfig object as 'config'
                safety_settings=safety_settings_list, # Pass safety settings list directly here
                stream=False # Stream is a direct parameter to generate_content
            )
            # --- END CRITICAL FIX ---
            
            if response.candidates:
                return response.candidates[0].content
            else:
                print(f"No candidates returned. Prompt feedback: {response.prompt_feedback}")
                return Content(parts=[Part(text="No response generated due to safety settings or other issues.")])

        except Exception as e:
            print(f"Error calling Gemini API with tools: {e}")
            raise # Re-raise the exception to be handled by the main app


    def generate_response(self, prompt: str) -> str:
        """
        Generates a simple text response without tool awareness.
        Converts a string prompt to the required contents format.
        """
        try:
            contents_for_simple_gen = [Part(text=prompt)]

            # For simple generate_response, we don't need tools/tool_config/safety_settings
            # so we just pass model and contents
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents_for_simple_gen
            )
            return response.text
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            return "I'm sorry, I couldn't generate a response at this time."

# --- Example Usage (for testing this module independently) ---
if __name__ == "__main__":
    llm_client = GeminiLLMInterface()

    print("--- Testing simple text generation ---")
    test_prompt_simple = "Tell me a fun fact about the universe."
    response_text = llm_client.generate_response(test_prompt_simple)
    print(f"Gemini's text response: {response_text}")

    print("\n--- Testing tool call (requires a tool definition) ---")
    
    mock_function_declaration_for_gemini = {
        "name": "mock_display_message",
        "description": "A mock tool to display a message on a screen.",
        "parameters": {
            "type": "OBJECT", # Always uppercase
            "properties": {
                "message": {"type": "STRING"} # Always uppercase
            },
            "required": ["message"]
        }
    }

    mock_messages_for_tool_call = [
        {"role": "user", "parts": [Part(text="Can you display 'Hello world' for me using your display tool?")]}
    ]

    try:
        async def _test_tool_call_async():
            tool_response_content = await llm_client.generate_response_with_tools(
                messages_history=mock_messages_for_tool_call,
                tools=[mock_function_declaration_for_gemini] # Pass the FLAT list of FunctionDeclaration dicts
            )
            
            if tool_response_content and tool_response_content.parts:
                for part in tool_response_content.parts:
                    if part.function_call:
                        func_call = part.function_call
                        print(f"LLM requested mock tool: {func_call.name} with args {func_call.args}")
                    elif part.text:
                        print(f"LLM text response: {part.text}")
            else:
                print("LLM did not generate a response part (might be blocked or no output).")

        asyncio.run(_test_tool_call_async())
    except Exception as e:
        print(f"Error during tool call test: {e}")