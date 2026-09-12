from __future__ import annotations
#导入 annotations 让类型注解延后处理

import os 
#导入 Python 自带的 os 模块，用于与操作系统交互

from dotenv import load_dotenv
#从第三方库 python-dotenv 中导入 load_dotenv 函数。 调用它可以把 .env 文件中的配置加载到环境变量中：load_dotenv()
#可以通过 os.getenv("API_KEY")

from langchain_openai import ChatOpenAI
#从第三方库 langchain-openai 中导入 ChatOpenAI 类 
#用于在 LangChain 中调用 OpenAI 聊天模型，也可以通过 base_url 连接兼容 OpenAI 接口的服务

def create_model() -> ChatOpenAI:
    load_dotenv()
    #调用这个函数，让它把 .env 文件中的配置加载到当前 Python 进程的环境变量里

    api_key = os.getenv("API_KEY")
    model = os.getenv("MODEL")
    base_url = os.getenv("BASE_URL")
    #用 os.getenv() 读取这些环境变量

    missing = [name for name, value in {"API_KEY": api_key, "MODEL": model, "BASE_URL": base_url}.items() if not value]
    if missing:
        raise RuntimeError(f"missing required .env setting(s): {', '.join(missing)}")
    #查找是否所有参数都读到了 缺失则抛出异常

    return ChatOpenAI(
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0,
    )
    #返回env参数