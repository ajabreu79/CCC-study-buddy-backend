from typing import List
import asyncio
import re

from pydantic import BaseModel
import openai
from openai.types.beta.threads import Run


class ChatSingleCallModel(BaseModel):
    dynamic_auth_code: str
    message: str
    thread_id: str | None = None


class ChatSingleCallResponse(BaseModel):
    status: str  # "success" or "fail"
    error_message: str | None = None
    messages: List[str]
    thread_id: str


class ChatSingleCall:
    """
    ChatSingleCall: AI chat with OpenAI Assistant API.
    Single call for each message, in contrast to ChatWebsocket.
    """

    def __init__(self, openai_client):
        self.openai_client = openai_client

    async def send_chat(self, chat_single_call_model: ChatSingleCallModel) -> ChatSingleCallResponse:
        """
        Send a message to OpenAI API.
        :param chat_single_call_model:
        :return:
        """
        user_message = chat_single_call_model.message
        if chat_single_call_model.thread_id is not None and self.__check_thread_id_format(
                chat_single_call_model.thread_id):
            thread_id = chat_single_call_model.thread_id
        else:
            thread_id = self.__create_thread()
        # add message to thread
        add_message_status = self.__add_message_to_thread(thread_id, user_message)
        if not add_message_status:
            return ChatSingleCallResponse(status="fail", messages=[], thread_id=thread_id, error_message="Your previous message was still processing. Please wait a moment and try again.")
        # run assistant
        run = self.openai_client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id="asst_lIKqjB7CvqRjxzzkXmNKSFi9",
            instructions="",
        )
        # poll the run status
        run = await self.__poll_run_status(run.id, thread_id)
        # get the response messages
        thread_messages = self.openai_client.beta.threads.messages.list(thread_id=run.thread_id)
        response_messages = []
        for message in thread_messages.data:
            if message.role == "assistant":
                for single_message in message.content:
                    if single_message.type == "text":
                        response_messages.append(single_message.text.value)
            elif message.role == "user":
                break
        # reverse the list
        response_messages.reverse()
        return ChatSingleCallResponse(status="success", messages=response_messages, thread_id=thread_id)

    async def __poll_run_status(self, run_id: str, thread_id: str) -> Run:
        """
        poll the run status
        :param thread_id: the thread id for this conversation
        :param run_id: run id in string
        :return: run status in string
        """
        while True:
            run = self.openai_client.beta.threads.runs.retrieve(
                run_id=run_id,
                thread_id=thread_id,
            )
            if run.status == "completed":
                return run
            else:
                await asyncio.sleep(0.2)

    def __create_thread(self) -> str:
        """
        Create a new thread in OpenAI API.
        :return: thread_id
        """
        thread = self.openai_client.beta.threads.create()
        return thread.id

    def __add_message_to_thread(self, thread_id: str, message: str):
        """
        Add a message to a thread in OpenAI API.
        :param thread_id: thread_id
        :param message: message
        :return:
        """
        try:
            self.openai_client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message
            )
            return True
        except openai.BadRequestError as e:
            print(f"Error: {e}")
            return False

    @staticmethod
    def __check_thread_id_format(thread_id: str) -> bool:
        """
        Check if the thread_id is in the correct format.
        regex: thread_[a-zA-Z0-9]+
        :param thread_id:
        :return:
        """
        return bool(re.match(r"thread_[a-zA-Z0-9]+", thread_id))
