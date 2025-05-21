from pathlib import Path
from datetime import datetime
import time
import queue
import os

from streamlit_webrtc import WebRtcMode, webrtc_streamer
import streamlit as st

import pydub
import openai
from dotenv import load_dotenv, find_dotenv

# Carrega variáveis de ambiente do arquivo .env
_ = load_dotenv(find_dotenv())

# Obtém a chave da API do ambiente em vez de colocá-la diretamente no código
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise ValueError("Nenhuma chave de API OpenAI encontrada. Por favor, configure a variável de ambiente OPENAI_API_KEY.")

PASTA_ARQUIVOS = Path(__file__).parent / 'arquivos'
PASTA_ARQUIVOS.mkdir(exist_ok=True)

PROMPT = '''
Faça o reumo do texto delimitado por #### 
O texto é a transcrição de uma reunião.
O resumo deve contar com os principais assuntos abordados.
O resumo deve ter no máximo 300 caracteres.
O resumo deve estar em texto corrido.
No final, devem ser apresentados todos acordos e combinados 
feitos na reunião no formato de bullet points.

O formato final que eu desejo é:

Resumo reunião:
- escrever aqui o resumo.

Acordos da Reunião:
- acrodo 1
- acordo 2
- acordo 3
- acordo n

texto: ####{}####
'''


def salva_arquivo(caminho_arquivo, conteudo):
    with open(caminho_arquivo, 'w') as f:
        f.write(conteudo)

def le_arquivo(caminho_arquivo):
    if caminho_arquivo.exists():
        with open(caminho_arquivo) as f:
            return f.read()
    else:
        return ''

def listar_reunioes():
    lista_reunioes = PASTA_ARQUIVOS.glob('*')
    lista_reunioes = list(lista_reunioes)
    lista_reunioes.sort(reverse=True)
    reunioes_dict = {}
    for pasta_reuniao in lista_reunioes:
        data_reuniao = pasta_reuniao.stem
        ano, mes, dia, hora, min, seg = data_reuniao.split('_')
        reunioes_dict[data_reuniao] = f'{ano}/{mes}/{dia} {hora}:{min}:{seg}'
        titulo = le_arquivo(pasta_reuniao / 'titulo.txt')
        if titulo != '':
            reunioes_dict[data_reuniao] += f' - {titulo}'
    return reunioes_dict


# OPENAI UTILS =====================
client = openai.OpenAI(api_key=openai.api_key)


def transcreve_audio(caminho_audio, language='pt', response_format='text'):
    with open(caminho_audio, 'rb') as arquivo_audio:
        transcricao = client.audio.transcriptions.create(
            model='whisper-1',
            language='pt',
            response_format='text',
            file=arquivo_audio,
            temperature=0.0
        )
        print(f"Transcription result: {transcricao}")  # Debug log
        return transcricao.strip()


def chat_openai(
        mensagem,
        modelo='gpt-3.5-turbo-1106',
    ):
    mensagens = [{'role': 'user', 'content': mensagem}]
    resposta = client.chat.completions.create(
        model=modelo,
        messages=mensagens,
        )
    return resposta.choices[0].message.content

# TAB GRAVA REUNIÃO =====================

def adiciona_chunck_audio(frames_de_audio, audio_chunck):
    for frame in frames_de_audio:
        sound = pydub.AudioSegment(
            data=frame.to_ndarray().tobytes(),
            sample_width=frame.format.bytes,
            frame_rate=frame.sample_rate,
            channels=len(frame.layout.channels),
        )
        audio_chunck += sound
    return audio_chunck




def tab_grava_reuniao():
    webrtx_ctx = webrtc_streamer(
        key='recebe_audio',
        mode=WebRtcMode.SENDONLY,
        audio_receiver_size=1024,
        media_stream_constraints={'video': False, 'audio': True},
    )

    if not webrtx_ctx.state.playing:
        return

    container = st.empty()
    container.markdown('Comece a falar')
    pasta_reuniao = PASTA_ARQUIVOS / datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
    pasta_reuniao.mkdir()

    ultima_trancricao = time.time()
    audio_completo = pydub.AudioSegment.empty()
    audio_chunck = pydub.AudioSegment.empty()
    transcricao = ''

    while True:
        if webrtx_ctx.audio_receiver:
            try:
                frames_de_audio = webrtx_ctx.audio_receiver.get_frames(timeout=1)
            except queue.Empty:
                time.sleep(0.1)
                continue
            audio_completo = adiciona_chunck_audio(frames_de_audio, audio_completo)
            audio_chunck = adiciona_chunck_audio(frames_de_audio, audio_chunck)
            if len(audio_chunck) > 0:
                audio_completo.export(pasta_reuniao / 'audio.mp3')
                agora = time.time()
                if agora - ultima_trancricao > 5:
                    ultima_trancricao = agora
                    audio_chunck.export(pasta_reuniao / 'audio_temp.mp3')
                    transcricao_chunck = transcreve_audio(pasta_reuniao / 'audio_temp.mp3')
                    transcricao += transcricao_chunck
                    salva_arquivo(pasta_reuniao / 'transcricao.txt', transcricao)
                    container.markdown(transcricao)
                    audio_chunck = pydub.AudioSegment.empty()
        else:
            break

# TAB SELEÇÃO REUNIÃO =====================
def tab_selecao_reuniao():
    reunioes_dict = listar_reunioes()
    if len(reunioes_dict) > 0:
        reuniao_selecionada = st.selectbox('Selecione uma reunião',
                                        list(reunioes_dict.values()))
        st.divider()
        reuniao_data = [k for k, v in reunioes_dict.items() if v == reuniao_selecionada][0]
        pasta_reuniao = PASTA_ARQUIVOS / reuniao_data
        if not (pasta_reuniao / 'titulo.txt').exists():
            st.warning('Adicione um titulo')
            titulo_reuniao = st.text_input('Título da reunião')
            st.button('Salvar',
                      on_click=salvar_titulo,
                      args=(pasta_reuniao, titulo_reuniao))
        else:
            titulo = le_arquivo(pasta_reuniao / 'titulo.txt')
            transcricao = le_arquivo(pasta_reuniao / 'transcricao.txt')
            resumo = le_arquivo(pasta_reuniao / 'resumo.txt')
            if resumo == '':
                gerar_resumo(pasta_reuniao)
                resumo = le_arquivo(pasta_reuniao / 'resumo.txt')
            
            # Removida a mensagem "Nenhuma transcrição encontrada" quando há transcrição
            st.markdown(f'## {titulo}')
            st.markdown(f'{resumo}')
            st.markdown(f'Transcricao: {transcricao}')
    else:
        st.markdown('<div class="empty-state">Nenhuma transcrição encontrada</div>', 
                   unsafe_allow_html=True)

            
        
def salvar_titulo(pasta_reuniao, titulo):
    salva_arquivo(pasta_reuniao / 'titulo.txt', titulo)

def gerar_resumo(pasta_reuniao):
    transcricao = le_arquivo(pasta_reuniao / 'transcricao.txt')
    resumo = chat_openai(mensagem=PROMPT.format(transcricao))
    salva_arquivo(pasta_reuniao / 'resumo.txt', resumo)


# MAIN =====================
def main():
    # Configuração da página
    st.set_page_config(
        page_title="Transcritor",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

    # CSS e estrutura do layout elegante
    st.markdown("""
    <style>
        /* Reset e variáveis */
        :root {
            --primary: #15adb7;
            --dark: #0a1628;
            --card: rgba(255, 255, 255, 0.05);
            --border: rgba(255, 255, 255, 0.08);
        }

        .stApp {
            background: linear-gradient(125deg, #080b14, #0f1b2d);
        }

        /* Overlay de luz no fundo */
        .stApp::before {
            content: '';
            position: fixed;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: repeating-linear-gradient(
                transparent,
                rgba(21, 173, 183, 0.03) 50%
            );
            transform: rotate(30deg);
            pointer-events: none;
        }

        /* Header com efeito de vidro */
        .header {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border);
            padding: 1.5rem;
            margin: -1rem -1rem 2rem -1rem;
        }

        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .logo {
            font-size: 1.5rem;
            color: white;
            font-weight: 200;
            letter-spacing: 1px;
        }

        .logo span {
            color: var(--primary);
            font-weight: 500;
        }

        /* Cards com efeito de vidro e borda luminosa */
        .glass-card {
            background: var(--card);
            backdrop-filter: blur(20px);
            border-radius: 16px;
            padding: 2rem;
            border: 1px solid var(--border);
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease;
        }

        .glass-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(
                90deg,
                transparent,
                rgba(21, 173, 183, 0.1),
                transparent
            );
            transition: 0.5s;
        }

        .glass-card:hover::before {
            left: 100%;
        }

        /* Títulos das seções */
        .section-title {
            color: white;
            font-size: 1.25rem;
            font-weight: 300;
            letter-spacing: 0.5px;
            margin-bottom: 2rem;
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .icon-box {
            background: rgba(21, 173, 183, 0.1);
            padding: 0.75rem;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        /* Botão com efeito neon */
        .stButton>button {
            background: var(--primary) !important;
            color: white !important;
            padding: 1rem !important;
            border-radius: 12px !important;
            border: none !important;
            font-weight: 400 !important;
            letter-spacing: 1px !important;
            text-transform: uppercase !important;
            width: 100%;
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease !important;
            box-shadow: 0 0 15px rgba(21, 173, 183, 0.3) !important;
        }

        .stButton>button:hover {
            transform: translateY(-2px);
            box-shadow: 0 0 25px rgba(21, 173, 183, 0.5) !important;
        }

        /* Select elegante */
        .stSelectbox > div {
            background: transparent !important;
        }

        .stSelectbox > div > div {
            background: rgba(0, 0, 0, 0.2) !important;
            border: 1px solid var(--border) !important;
            border-radius: 12px !important;
            color: rgba(255, 255, 255, 0.7) !important;
            padding: 1rem !important;
            transition: all 0.3s ease;
        }

        .stSelectbox > div > div:hover {
            border-color: var(--primary) !important;
            box-shadow: 0 0 15px rgba(21, 173, 183, 0.1);
        }

        /* Estado vazio */
        .empty-state {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 2rem;
            color: rgba(255, 255, 255, 0.5);
            text-align: center;
        }

        /* Remover elementos do Streamlit */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        /* Grid responsivo */
        .grid-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 1rem;
        }
    </style>

    <div class="header">
        <div class="header-content">
            <h1 class="logo"><span>Aions</span> Transcritor</h1>
        </div>
    </div>

    <div class="grid-container">
    """, unsafe_allow_html=True)

    # Layout principal
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="glass-card">
            <div class="section-title">
                <div class="icon-box">🎤</div>
                Nova Gravação
            </div>
        """, unsafe_allow_html=True)
        
        tab_grava_reuniao()
        
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="glass-card">
            <div class="section-title">
                <div class="icon-box">📝</div>
                Transcrições
            </div>
        """, unsafe_allow_html=True)
        
        tab_selecao_reuniao()
        
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

if __name__ == '__main__':
    main()