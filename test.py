# from TTS.api import TTS
# import os

# tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

# text = "Salam sir, aap ka pizza ready hai."

# tts.tts_to_file(
#     text=text,
#     speaker=None,   # use default speaker
#     speaker_wav="imrankhan.wav",  # path to speaker reference audio
#     language="hi",
#     file_path="output.wav"
# )

# os.system("start output.wav")
from gtts import gTTS
import os

text = "Salam sir, aap ka pizza ready hai."
tts = gTTS(text=text, lang="hi", tld="com.pk")
tts.save("output.mp3")
os.system("start output.mp3")
