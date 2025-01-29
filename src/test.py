# Copyright (c) 2024.
# -*-coding:utf-8 -*-
"""
@file: test.py
@author: Jerry(Ruihuang)Yang
@email: rxy216@case.edu
@time: 3/14/24 19:52
"""
import os

import openai
from dotenv import load_dotenv
from typing_extensions import override
from openai import AssistantEventHandler


# First, we create a EventHandler class to define
# how we want to handle the events in the response stream.

class EventHandler(AssistantEventHandler):
    @override
    def on_text_created(self, text) -> None:
        print(f"\nassistant > ", end="", flush=True)

    @override
    def on_text_delta(self, delta, snapshot):
        print(delta.value, end="", flush=True)

    def on_tool_call_created(self, tool_call):
        print(f"\nassistant > {tool_call.type}\n", flush=True)

    def on_tool_call_delta(self, delta, snapshot):
        if delta.type == 'code_interpreter':
            if delta.code_interpreter.input:
                print(delta.code_interpreter.input, end="", flush=True)
            if delta.code_interpreter.outputs:
                print(f"\n\noutput >", flush=True)
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        print(f"\n{output.logs}", flush=True)


# Then, we use the `create_and_stream` SDK helper
# with the `EventHandler` class to create the Run
# and stream the response.

load_dotenv()

client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

with client.beta.threads.runs.create_and_stream(
        thread_id="thread_1kubegLv1nm1s6yFNMAyQ3Bo",
        assistant_id="asst_lIKqjB7CvqRjxzzkXmNKSFi9",
        instructions="This is a test run. Please repeat the thing I can help you today 20 times.",
        event_handler=EventHandler(),
) as stream:
    stream.until_done()
