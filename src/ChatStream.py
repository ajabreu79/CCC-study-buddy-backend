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
from src.TtsStream import TtsStream
import uuid


class ChatStreamModel(BaseModel):
    dynamic_auth_code: str
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
        # generate a TtsStream session id (uuid4)
        self.tts_session_id = str(uuid.uuid4())
        self.tts = TtsStream(self.tts_session_id)

    def stream_chat(self, chat_stream_model: ChatStreamModel):
        """
        Stream chat messages from OpenAI API.
        :return:
        """
        messages = self.__messages_processor(chat_stream_model.messages)
        return EventSourceResponse(self.__chat_generator(messages))

    def __chat_generator(self, messages: List[dict[str, str]]):
        """
        Chat generator.
        :param messages:
        :return:
        """
        if self.requested_provider == "openai-4-general" or self.requested_provider == "openai":
            print("Using OpenAI gpt-4-turbo general")
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
        chunk_id = -1  # chunk_id starts from 0, -1 means no chunk has been created
        sentence_ender = [".", "?", "!"]
        chunk_buffer = ""
        for text_chunk in stream:
            new_text = text_chunk
            response_text += new_text
            if len(chunk_buffer.split()) > 21 or (chunk_id == -1 and len(
                    chunk_buffer.split()) > 5):  # if the chunk is more than 21 words, or the first chunk is more than 5 words
                if sentence_ender[0] in new_text:  # if the chunk contains a sentence ender .
                    chunk_buffer, chunk_id = self.__process_chunking(sentence_ender[0], new_text, chunk_buffer,
                                                                     chunk_id)
                elif sentence_ender[1] in new_text:  # if the chunk contains a sentence ender ?
                    chunk_buffer, chunk_id = self.__process_chunking(sentence_ender[1], new_text, chunk_buffer,
                                                                     chunk_id)
                elif sentence_ender[2] in new_text:  # if the chunk contains a sentence ender !
                    chunk_buffer, chunk_id = self.__process_chunking(sentence_ender[2], new_text, chunk_buffer,
                                                                     chunk_id)
                else:  # if the chunk does not contain a sentence ender
                    chunk_buffer += new_text
            else:  # if the chunk is less than 21 words
                chunk_buffer += new_text
            yield json.dumps(
                {"response": response_text, "tts_session_id": self.tts_session_id,
                 "tts_max_chunk_id": chunk_id})
        # Process any remaining text in the chunk_buffer after the stream has finished
        if chunk_buffer:
            chunk_id += 1
            self.tts.stream_tts(chunk_buffer, str(chunk_id))
            yield json.dumps(
                {"response": response_text, "tts_session_id": self.tts_session_id, "tts_max_chunk_id": chunk_id})

    def __openai_chat_generator(self, messages: List[dict[str, str]], model_name="gpt-4o-2024-08-06"):
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

    def __anthropic_chat_generator(self, messages: List[dict[str, str]]):
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
                model="claude-3-5-sonnet-20240620",
                temperature=0.9,
        ) as stream:
            for text in stream.text_stream:
                if text is not None:
                    yield text

    def __process_chunking(self, sentence_ender: str, new_text: str, chunk_buffer: str, chunk_id: int):
        """
        Process the chunking.
        :param sentence_ender:
        :param new_text:
        :param chunk_buffer:
        :param chunk_id:
        :return:
        """
        chunk_id += 1
        new_text_split = new_text.split(sentence_ender)
        chunk_buffer += new_text_split[0] + sentence_ender
        self.tts.stream_tts(chunk_buffer, str(chunk_id))
        chunk_buffer = sentence_ender.join(new_text_split[1:])
        return chunk_buffer, chunk_id

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
        for key in sorted(messages.keys()):
            messages_list.append(messages[key])
        return messages_list
