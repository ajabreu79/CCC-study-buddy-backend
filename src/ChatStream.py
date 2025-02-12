# Copyright (c) 2024.
# -*-coding:utf-8 -*-
"""
@file: ChatStream.py
@author: Jerry(Ruihuang)Yang
@email: rxy216@case.edu
@time: 2/29/24 15:14
"""
from typing import List
import json
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


class ChatStreamModel(BaseModel):
    messages: dict[int, dict[str, str]]
    thread_id: str | None = None
    provider: str = "openai"


class ChatStreamResponse(BaseModel):
    status: str  # "success" or "fail"
    error_message: str | None = None
    messages: List[str]
    thread_id: str


class ChatStream:
    """
    ChatStream: AI chat with OpenAI/Anthropic, streams the output via server-sent events.
    Using this class need to pass in the full messages history, and the provider (openai or anthropic).
    """

    def __init__(self, requested_provider, openai_client, anthropic_client):
        self.requested_provider = requested_provider
        self.openai_client = openai_client
        self.anthropic_client = anthropic_client

    def stream_chat(self, chat_stream_model: ChatStreamModel):
        """
        Stream chat messages from OpenAI API.
        :return:
        """
        messages = self.__messages_processor(chat_stream_model.messages)
        response_text = ""
        for new_text in self.__chat_generator(messages):
            response_text = new_text["response"]
        return {"response": response_text}

    def __chat_generator(self, messages: List[dict[str, str]]):
        """
        Chat generator.
        :param messages:
        :return:
        """
        if self.requested_provider == "openai-4-general" or self.requested_provider == "openai":
            print("Using OpenAI gpt-4o general")
            stream = self.__openai_chat_generator(messages)
        elif self.requested_provider == "openai-35-fine-tune":
            print("Using OpenAI gp-3.5-turbo fine-tuned")
            # add prompt to make the system a little bit angry
            messages[0]["content"] = messages[0]["content"] + "You are a bit annoyed and impatient."
            stream = self.__openai_chat_generator(messages,
                                                  model_name="ft:gpt-3.5-turbo-1106:genai-in-teaching:progressivef24:9CeDEoUZ")
        elif self.requested_provider == "openai-35-general":
            print("Using OpenAI gpt-3.5-turbo general")
            stream = self.__openai_chat_generator(messages, model_name="gpt-4o-mini")
        elif self.requested_provider == "anthropic":
            print("Using Anthropic")
            stream = self.__anthropic_chat_generator(messages)
        else:
            stream = self.__openai_chat_generator(messages)
        response_text = ""
        for new_text in stream:
            response_text += new_text
            # Yield only the response text:
            yield {"response": response_text}

    def __openai_chat_generator(self, messages: List[dict[str, str]], model_name="gpt-4o-2024-11-20"):
        """
        OpenAI chat generator.
        :param messages:
        :return:
        """
        with self.openai_client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=True,
                temperature=0.9,
        ) as stream:
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    new_text = chunk.choices[0].delta.content
                    yield new_text

    def __anthropic_chat_generator(self, messages: List[dict[str, str]], model_name="claude-3-5-sonnet-20241022"):
        """
        Anthropic chat generator.
        :param messages:
        :return:
        """
        system_message_content = ""
        if messages[0]["role"] == "system":
            system_message = messages.pop(0)
            system_message_content = system_message["content"]
        with self.anthropic_client.messages.stream(
                system=system_message_content,
                max_tokens=2048,
                messages=messages,
                model=model_name,
                temperature=0.9,
        ) as stream:
            for text in stream.text_stream:
                if text is not None:
                    yield text

    def __messages_processor(self, messages: dict[int, dict[str, str]]):
        """
        Process the message.
        :param messages: {0: {"role": "user", "content": "Hello, how are you?"}, 1: {"role": "assistant", "content": "I am fine, thank you."}}
        :return:
        """
        messages_list = [{"role": "system",
                          "content": "You are a Simulated Crown Insurance Customer on a phone call to Crown customer service. Crown Insurance is one of the largest auto insurance companies in the country. Remember, You are the customer, NOT the customer service representative. Remember, You are the customer, NOT the customer service representative. Your name is Jordan Smith. You need to add a vehicle to your insurance policy. The vehicle you want to add is a 2023 Honda Civic. The Zip code you are in is 44106. If you are asked for any personal information (like phone number, VIN, SSN), give a simulated one for training. Make sure you talk like you are on a phone call."},
                         {"role": "user",
                          "content": "Call Start."},
                         {"role": "assistant",
                          "content": "Have I reached Crown customer service? I'm a Crown customer."},
                         {"role": "user",
                          "content": "Yes, this is Crown customer service. I'm a customer service representative."},
                         {"role": "assistant",
                          "content": "hi."}]
        ## This needs to be updated
        for key in sorted(messages.keys()):
            messages_list.append(messages[key])
        return messages_list
