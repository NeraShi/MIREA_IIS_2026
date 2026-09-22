"""
app.py — веб-интерфейс на Streamlit.

ПРАКТИКА 6. Что делает студент:
  1. довести оформление диалога под свой домен (заголовок, подсказки, приветствие)
  2. проверить, что кнопка очистки действительно сбрасывает и историю, и автомат

Готово: изолированные сессии, вызов ядра, отрисовка истории, плашка
офлайн-заглушки LLM.

Критерии приёмки:
  - интерфейс принимает ввод и показывает историю диалога
  - кнопка очистки сбрасывает сессию: после неё система не помнит прошлых реплик
  - две вкладки браузера — две независимые сессии

Про безопасность (П7). Проверки ввода здесь нет намеренно: guardrail живёт в ядре
и одинаково защищает и этот интерфейс, и VK-бота. Не переносите его сюда — иначе
вторым каналом защиту можно будет обойти.

Запуск:
    streamlit run app.py
"""

import uuid

import streamlit as st

import config
from orchestrator import Orchestrator

st.set_page_config(page_title="Справочный ассистент", page_icon="🔎")


@st.cache_resource
def get_orchestrator() -> Orchestrator:
    """Одно ядро на всё приложение: MCP-сессия и модель поднимаются один раз."""
    return Orchestrator()


# Изолированная сессия на вкладку браузера
if "session_id" not in st.session_state:
    st.session_state.session_id = f"web:{uuid.uuid4()}"
if "history" not in st.session_state:
    st.session_state.history = []

orchestrator = get_orchestrator()

# TODO (П6): замените заголовок и подсказку на свои
st.title("Справочный ассистент")
st.caption("Отвечает по загруженной базе знаний и ссылается на источники.")

# Готовая часть, не убирать: на офлайн-заглушке ответы выглядят осмысленно,
# и без плашки это легко принять за работающую систему — в том числе на защите.
if config.LLM_BACKEND == "fake":
    st.warning(
        "Работает офлайн-заглушка LLM (`LLM_BACKEND=fake`): ответы собраны "
        "из найденных фрагментов, модель не вызывается. Для сдачи практик "
        "4, 6 и 8 переключитесь на `gigachat` или `ollama`."
    )

with st.sidebar:
    st.subheader("Сессия")
    st.code(st.session_state.session_id, language=None)
    if st.button("Очистить сессию", use_container_width=True):
        orchestrator.reset(st.session_state.session_id)
        st.session_state.history = []
        st.session_state.session_id = f"web:{uuid.uuid4()}"
        st.rerun()

for role, content in st.session_state.history:
    with st.chat_message(role):
        st.markdown(content)

if question := st.chat_input("Задайте вопрос по базе знаний"):
    st.session_state.history.append(("user", question))
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Ищу в базе знаний…"):
            answer = orchestrator.handle(st.session_state.session_id, question)
        st.markdown(answer)

    st.session_state.history.append(("assistant", answer))
