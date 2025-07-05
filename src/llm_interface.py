# llm_interface.py (Final Corrected for google-genai, version 5 - this *has* to be it!)

import os
from dotenv import load_dotenv
from google import genai
#from google.genai import types
import asyncio # Needed for async examples
from google.genai.types import (
    GenerateContentConfig,
    FunctionCallingConfig,
    HarmCategory,
    HarmBlockThreshold,
    Content, # Re-import Content if not already
    Part     # Re-import Part if not already
)


# Load environment variables from .env file
load_dotenv()

class GeminiLLMInterface:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables. Please set it in your .env file.")

        # 1. Initialize the Client with the API key.
        self.client = genai.Client(api_key=api_key)

        # 2. Access the GenerativeModel THROUGH the client's 'models' attribute.
        #self.model = self.client.models.GenerativeModel('gemini-pro') # Or 'gemini-1.5-flash', etc.
        self.model='gemini-2.0-flash-001'


    async def generate_response_with_tools(self, messages: list, tools: list):
        """
        Generates a response from the Gemini model, optionally using provided tools.

        Args:
            messages (list): A list of messages for the chat history, in Gemini format.
                             Example: [{"role": "user", "parts": [{"text": "Hello"}]}, ...]
            tools (list): A list of tool definitions (e.g., from mcp_server.mcp.get_tools()).
                          Gemini's SDK automatically converts these to its required format.
        Returns:
            google.generativeai.types.GenerateContentResponse: The full response object.
        """
        try:
            config = GenerateContentConfig(
                # 'tools' expects a list of dictionaries, where each dict is a FunctionDeclaration.
                tools=[{"function_declarations": tools}], # CRITICAL: wrap the list of tools in a "function_declarations" dictionary
                tool_config=FunctionCallingConfig(mode="AUTO") # Use string "AUTO"
            )
            
            safety_settings = [
                {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
                {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
                {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
            ]

            response = self.client.models.generate_content(
                model=self.model,
                contents=messages,
                config=config,
                #safety_settings=safety_settings,
                #stream=False
            )

            # Ensure we return the content directly from the candidate
            # response.candidates is a list, and content is a part of each candidate.
            if response.candidates:
                return response.candidates[0].content
            else:
                # Handle cases where no candidates are returned (e.g., safety block)
                print(f"No candidates returned. Prompt feedback: {response.prompt_feedback}")
                return genai.types.Content(parts=[genai.types.Part(text="No response generated.")])

        except Exception as e:
            print(f"Error calling Gemini API with tools: {e}")
            raise # Re-raise the exception to be handled by the main app


    def generate_response(self, prompt: str):
        """Generates a simple text response without tool awareness."""
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=prompt
            )
            return response.text
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            return "I'm sorry, I couldn't generate a response at this time."

# Example usage (for testing, will be integrated into main.py)
if __name__ == "__main__":
    llm_client = GeminiLLMInterface()

    print("Testing simple text generation:")
    test_prompt = "Tell me a fun fact about the universe."
    response_text = llm_client.generate_response(test_prompt)
    print(f"Gemini's text response: {response_text}")

    print("\nTesting tool call (requires a tool definition in the prompt/context):")
    
    # --- CRITICAL CHANGE: The 'tools' parameter expects a list of dictionaries,
    # where each dictionary is a FunctionDeclaration. This is the direct API schema. ---
    mock_tool_definition_for_gemini = [ # This is now a list of tools
        {
            "name": "mock_display_message",
            "description": "A mock tool to display a message on a screen.",
            "parameters": {
                "type": "OBJECT", # Use "OBJECT" (uppercase)
                "properties": {
                    "message": {"type": "STRING"} # Use "STRING" (uppercase)
                },
                "required": ["message"]
            }
        }
    ]

    mock_messages = [
        {"role": "user", "parts": [{"text": "Can you display 'Hello world' for me using your display tool?"}]}
    ]

    try:
        async def _test_tool_call_async():
            # Pass the list of FunctionDeclaration dictionaries directly
            tool_response_content = await llm_client.generate_response_with_tools(
                messages=mock_messages,
                tools=mock_tool_definition_for_gemini # Pass the list directly
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