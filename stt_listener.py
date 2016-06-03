#!/usr/bin/env python

import speech_recognition as sr
from collections import deque
from pydub import AudioSegment
import subprocess
import pyaudio
import wave
import audioop
import time
import math
import alsaaudio
import base64
import json
import requests
import os

# We need a WAV to FLAC converter. flac is available on Linux
FLAC_CONV = 'flac -f'

# Microphone stream config.
NUM_OF_SAMPLES = 50

FORMAT = pyaudio.paInt16

FORMAT_ALSA = alsaaudio.PCM_FORMAT_S16_LE

# 1 = mono, 2 = stereo, and 6 = full 6 channel audio.
CHANNELS = 1

# 8000-telephone, 16000, 44100(CD), 48000 (DVD) and 96000
RATE = 16000

# CHUNKS of bytes to read each time from mic
# Sets the actual period size in frames. Each write should
# consist of exactly this number of frames,
# and each read will return this number of frames
# (unless the device is in PCM_NONBLOCK mode, in which case it
# may return nothing at all)
CHUNK = 1024
PERIOD = CHUNK

WAV_FRAME_RATE = 16000

# The SPEECH_THRESHOLD intensity that defines silence
# and noise signal (an int. lower than SPEECH_THRESHOLD is silence).
SPEECH_THRESHOLD = 1500

# Silence limit in seconds. The max ammount of seconds where
# only silence is recorded. When this time passes the
# recording finishes and the file is delivered.
SILENCE_LIMIT = 1

# Previous audio (in seconds) to prepend. When noise
PREV_AUDIO = 0.5

# is detected, how much of previously recorded audio is
# prepended. This helps to prevent chopping the beggining
# of the phrase.
SILENCE_LIMIT = 1

WAVE_OUTPUT_FILENAME = 'recording.wav'
FLAC_OUTPUT_FILENAME = 'recording.flac'

GOOGLE_API_KEY = 'AIzaSyChAyl9GLDo4edb6N4go74DzcAwXFri8f0'
HTTP_API_BASE = 'https://speech.googleapis.com'
HTTP_API_CALL = "v1/speech:recognize?key={}".format(GOOGLE_API_KEY)
HTTP_URL = "{}/{}".format(HTTP_API_BASE, HTTP_API_CALL)

# IBM Watson credentials for STT & TTS services
IBM_USERNAME_STT = "d5b9ec82-468b-4950-81f1-3724fcbb416b"
IBM_PASSWORD_STT = "hypogOyEsjFf"
IBM_USERNAME_TTS = "7d03122a-fc83-4639-ab91-e4b9c74a4795"
IBM_PASSWORD_TTS = "2dVbmGiKLHWq"


def setup_mic():
    ''' Set up mic, capture audio, and return string of the result '''
    mic = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, device='pulse')
    mic.setchannels(CHANNELS)
    mic.setrate(RATE)
    mic.setformat(FORMAT_ALSA)
    mic.setperiodsize(CHUNK)
    return mic


def wav2flac(wav_file=WAVE_OUTPUT_FILENAME, flac_file=FLAC_OUTPUT_FILENAME):
    """ Converts WAVE file to FLAC
    """
    song = AudioSegment.from_wav(wav_file)
    song.export(flac_file, format="flac")


def write_flac(data, filename=None):
    """ Write string of data to WAV and converts to FLAC
        returns flac filename
    """
    if not filename:
        filename = 'output_'+str(int(time.time()))

    data = ''.join(data)
    wf = wave.open("{}.wav".format(filename), 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)
    wf.setframerate(RATE)
    wf.writeframes(data)
    wf.close()

    wav2flac("{}.wav".format(filename), "{}.flac".format(filename))
    return "{}.flac".format(filename)


def get_audio_intensity(num_samples=NUM_OF_SAMPLES):
    """ Gets average audio intensity of your mic sound. You can use it to get
        average intensities while you're talking and/or silent. The average
        is the avg of the 20% largest intensities recorded.
    """
    mic = setup_mic()
    values = [math.sqrt(abs(audioop.avg(mic.read()[1], 4)))
              for x in range(num_samples)]
    values = sorted(values, reverse=True)
    intensity = sum(values[:int(num_samples * 0.2)]) / int(num_samples * 0.2)
    print " Finished "
    print " Average audio intensity is ", intensity
    mic.close()
    return intensity


def speech_recognize(filename=FLAC_OUTPUT_FILENAME):
    """ This method converts FLAC file data to base64
        end sends it to google for STT recognitions
        Returns text ot None
    """
    if 'flac' not in filename:
        raise Exception('Not a Flac file format !!!')
        return None

    data64 = base64.b64encode(open(filename, 'rb').read())
    tmpJson = {
        "initialRequest": {
            "encoding": "FLAC",
            "sampleRate": 16000
        },
        "audioRequest": {
            "content": data64
        }
    }
    headers = {'content-type': 'application/json'}
    data2send = json.dumps(tmpJson)
    response = requests.post(HTTP_URL, data=data2send, headers=headers)
    if response.ok:
        answerJson = json.loads(response.text)
        try:
            results = answerJson['responses'][0]["results"][0]
            return results['alternatives'][0]['transcript']
        except:
            print '>>> Empty answer form Google!!!'
            return None
    else:
        return None


def listen_speech(SPEECH_THRESHOLD=SPEECH_THRESHOLD, num_phrases=-1):
    """
    Listens to Microphone with pyalsa module, extracts phrases
    from it and sends it to Google's TTS service and returns response.
    A "phrase" is sound surrounded by silence (according to SPEECH_THRESHOLD).
    'num_phrases' controls how many phrases to process before finishing
    the listening process (-1 for infinite).
    """
    mic = setup_mic()

    audio2send = []
    cur_data = ''  # current chunk  of audio data
    rel = RATE/CHUNK
    slid_win = deque(maxlen=SILENCE_LIMIT * rel)
    # Prepend audio from 0.5 seconds before noise was detected
    prev_audio = deque(maxlen=PREV_AUDIO * rel)
    started = False
    n = num_phrases
    response = []

    print "* Listening mic. "
    while (num_phrases == -1 or n > 0):
        cur_data = mic.read()[1]
        slid_win.append(math.sqrt(abs(audioop.avg(cur_data, 4))))
        # print slid_win[-1]
        if(sum([x > SPEECH_THRESHOLD for x in slid_win]) > 0):
            if(not started):
                print "Starting record of phrase"
                started = True
            audio2send.append(cur_data)
        elif (started is True):
            print "Finished recording"
            # The limit was reached, finish capture and deliver.
            filename = write_flac(list(prev_audio) + audio2send)

            print "Playing recorder speech before SST"
            play(filename)

            # Send file to Google and get response
            r = speech_recognize(filename)

            if num_phrases == -1:
                print "GOOGLE Response: ", r
            else:
                response.append(r)

            # Remove temp file. Comment line to review.
            os.remove(filename)

            # Reset all
            started = False
            slid_win = deque(maxlen=SILENCE_LIMIT * rel)
            prev_audio = deque(maxlen=0.5 * rel)
            audio2send = []
            n -= 1
            print "Listening ..."
        else:
            prev_audio.append(cur_data)

    print "* Done recording"
    mic.close()

    return response


def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print '%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0)
        return ret
    return wrap


# simple wrapper function to encode the username & pass
def encode_user_data(user, password):
    """
    Returns basic authentication object
    """
    return "Basic " + (user + ":" + password).encode("base64").rstrip()


@timing
def ibm_stt(timeout, audio=None):
    """
    Translates speech to text and prints execution time
    """

    # obtain audio from the microphone or get from outside
    if audio is None:
        r = sr.Recognizer()
        with sr.Microphone() as source:
            print("Say something!")
            audio = r.listen(source, timeout)

    try:
        text = r.recognize_ibm(audio, username=IBM_USERNAME_STT, password=IBM_PASSWORD_STT)
        print("You say: " + text)
    except sr.UnknownValueError:
        print("IBM Speech to Text could not understand audio")
    except sr.RequestError as e:
        print("Could not request results from IBM Speech to Text service; {0}".format(e))

    return text


@timing
def ibm_tts(text, sfile, username=IBM_USERNAME_TTS, password=IBM_PASSWORD_TTS):
    """
    Translates text to speech (wave file) and prints execution time
    """
    url = "https://stream.watsonplatform.net/text-to-speech/api/v1/synthesize"
    req = urllib2.Request(url)
    req.add_header('Accept', 'audio/wav')
    req.add_header("Content-type", "application/json")
    req.add_header('Authorization',encode_user_data(user=username, password=password))
    req.get_method = lambda: 'POST'
    req.add_data("{\"text\":\""+text+"\"}")
    try:
        fp = open(sfile, 'wb')
        res = urllib2.urlopen(req)
        for line in res:
            fp.write(line)
        fp.close()
    except urllib2.HTTPError:
        print "IBM error"

@timing
def play(audio_file_path):
    subprocess.call(["mplayer", audio_file_path], stdout=open(os.devnull, 'wb'))


if(__name__ == '__main__'):
    #listen_for_speech()  # listen to mic.
    #print stt_google_wav('output_1459452343.wav')  # translate audio file
    #audio_int_pyaudio()  # To measure your mic levels
    #audio_int_pyalsa()  # To measure your mic levels
    #TEXT = ibm_stt(10)

    #ibm_tts(TEXT)
    #play(TMP_FILE)


    listen_speech()

