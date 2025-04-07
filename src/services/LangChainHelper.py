import os
from typing import Dict, List, Any, Optional, Iterator, Union
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_pinecone import PineconeVectorStore
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from pydantic import SecretStr

from src.constants import SYSTEM, OPENAI_MODEL as DEFAULT_OPENAI_MODEL

# Initialize API keys from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)

# Initialize components
embeddings = OpenAIEmbeddings(api_key=SecretStr(OPENAI_API_KEY))


# Basic prompt template for RAG
RAG_SYSTEM_TEMPLATE = """You are an assistant for the Eaton Call Center, helping users with their questions.
You have access to the following context information from Eaton's documentation.
Use this context to inform your answers whenever relevant.

Context Information:
{context}

Remember:
1. If the answer is not in the context, use your general knowledge but make it clear that you're not drawing from Eaton's documentation.
2. If the context doesn't provide enough information to fully answer a question, acknowledge that and provide the best answer you can.
3. Always use information from the context over your general knowledge when they disagree.
4. Don't mention that you're using 'context' or 'documentation' in your answer - just provide the information naturally.
5. Cite sources at the end of your answer using [Source: document_name] format, if applicable.

User Query: {question}"""


def get_retriever(
    index_name: str,
    namespace: Optional[str] = None,
    agent_id: Optional[str] = None,
    top_k: int = 3,
    score_threshold: float = 0.7,
):
    """Get a retriever for querying Pinecone

    Args:
        index_name: The name of the Pinecone index
        namespace: Optional namespace to query within
        agent_id: Optional agent_id to filter by
        top_k: Number of results to retrieve
        score_threshold: Minimum similarity score to include results

    Returns:
        A configured retriever
    """
    # Create vector store
    vector_store = PineconeVectorStore(
        index_name=index_name,
        embedding=embeddings,
        namespace=namespace,
    )

    # Configure the retriever with metadata filtering
    search_kwargs = {"k": top_k, "score_threshold": score_threshold}

    # Add filter for agent_id if specified
    if agent_id:
        search_kwargs["filter"] = {"agent_id": agent_id}

    # Return the retriever
    return vector_store.as_retriever(
        search_type="similarity_score_threshold", search_kwargs=search_kwargs
    )


def format_chat_history(
    messages: List[Dict[str, str]],
) -> List[Union[HumanMessage, AIMessage, SystemMessage]]:
    """Format a list of message dictionaries into LangChain message objects

    Args:
        messages: List of message dictionaries with 'role' and 'content' keys

    Returns:
        List of LangChain message objects
    """
    formatted_messages = []
    for message in messages:
        role = message.get("role", "").lower()
        content = message.get("content", "")

        if role == "user":
            formatted_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            formatted_messages.append(AIMessage(content=content))
        elif role == "system":
            formatted_messages.append(SystemMessage(content=content))

    return formatted_messages


def chat_with_rag(
    query: str,
    agent_id: str,
    chat_history: List[Dict[str, str]] = None,
    system_prompt: str = None,
    index_name: str = "eaton-modules",
    top_k: int = 3,
) -> Dict[str, Any]:
    """Process a chat query using RAG to enhance the response

    Args:
        query: The user's query
        agent_id: The ID of the agent/module to query against
        chat_history: Optional list of previous chat messages
        system_prompt: Optional custom system prompt
        index_name: The Pinecone index name to query
        top_k: Number of results to retrieve

    Returns:
        Dict containing the response and source information
    """
    # Initialize chat history if not provided
    if chat_history is None:
        chat_history = []

    # Get retriever filtered by agent_id
    retriever = get_retriever(index_name=index_name, agent_id=agent_id, top_k=top_k)

    # Format system prompt
    if not system_prompt:
        system_prompt = RAG_SYSTEM_TEMPLATE

    # Create prompt template
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{question}")]
    )

    # Initialize LLM
    llm = ChatOpenAI(
        model_name=OPENAI_MODEL, api_key=SecretStr(OPENAI_API_KEY), temperature=0.7
    )

    # Initialize conversation memory
    memory = None
    if chat_history:
        memory = ConversationBufferMemory(
            memory_key="chat_history", return_messages=True
        )
        # Add chat history to memory
        for message in chat_history:
            role = message.get("role", "").lower()
            content = message.get("content", "")
            if role == "user":
                memory.chat_memory.add_user_message(content)
            elif role == "assistant":
                memory.chat_memory.add_ai_message(content)

    # Create chain
    chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        memory=memory,
        combine_docs_chain_kwargs={"prompt": prompt},
        return_source_documents=True,
    )

    # Execute chain
    response = chain({"question": query})

    # Extract source information
    sources = []
    if "source_documents" in response:
        for doc in response["source_documents"]:
            if hasattr(doc, "metadata"):
                sources.append(
                    {
                        "file_name": doc.metadata.get("file_name", "Unknown"),
                        "file_id": doc.metadata.get("file_id", ""),
                        "resource_id": doc.metadata.get("resource_id", ""),
                        "page_number": doc.metadata.get("page_number", 0),
                        "chunk_id": doc.metadata.get("chunk_id", 0),
                        "agent_id": doc.metadata.get("agent_id", ""),
                    }
                )

    return {"answer": response["answer"], "sources": sources}


def chat_stream_with_retrieve(
    query: str,
    agent_id: str,
    chat_history: List[Dict[str, str]] = None,
    system_prompt: str = None,
    index_name: str = "eaton-modules",
    top_k: int = 3,
) -> Iterator[str]:
    """Stream a chat response using RAG

    Args:
        query: The user's query
        agent_id: The ID of the agent/module to query against
        chat_history: Optional list of previous chat messages
        system_prompt: Optional custom system prompt
        index_name: The Pinecone index name to query
        top_k: Number of results to retrieve

    Yields:
        Chunks of the streaming response
    """
    # Initialize chat history if not provided
    if chat_history is None:
        chat_history = []

    # Get retriever filtered by agent_id
    retriever = get_retriever(index_name=index_name, agent_id=agent_id, top_k=top_k)

    # Retrieve relevant documents
    docs = retriever.get_relevant_documents(query)

    # Extract context from documents
    context_texts = [doc.page_content for doc in docs]
    context = "\n\n".join(context_texts)

    # Format system prompt with context
    if not system_prompt:
        system_prompt = RAG_SYSTEM_TEMPLATE

    formatted_system_prompt = system_prompt.format(context=context, question=query)

    # Format chat history for the model
    formatted_messages = [SystemMessage(content=formatted_system_prompt)]

    # Add chat history
    if chat_history:
        langchain_history = format_chat_history(chat_history)
        formatted_messages.extend(langchain_history)

    # Add current query
    formatted_messages.append(HumanMessage(content=query))

    # Initialize streaming LLM
    llm = ChatOpenAI(
        model_name=OPENAI_MODEL,
        api_key=SecretStr(OPENAI_API_KEY),
        temperature=0.7,
        streaming=True,
    )

    # Process response and stream
    for chunk in llm.stream(formatted_messages):
        if chunk.content:
            yield chunk.content

    # Add source information at the end
    if docs:
        yield "\n\nSources:\n"
        for i, doc in enumerate(docs):
            source_name = doc.metadata.get("file_name", f"Document {i+1}")
            yield f"[{i+1}] {source_name}\n"
