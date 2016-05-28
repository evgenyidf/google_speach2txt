#!/usr/bin/env python

import speech_recognition as sr
from collections import deque
from pydub import AudioSegment
import subprocess
import pyaudio
import wave
import audioop
import urllib2
import time
import math
import alsaaudio
import wave

# We need a WAV to FLAC converter. flac is available on Linux
FLAC_CONV = 'flac -f'

# Virtual device ID
vID = 1

# Microphone stream config.
NUM_OF_SAMPLES = 50
FORMAT = pyaudio.paInt16
FORMAT_ALSA = alsaaudio.PCM_FORMAT_S16_LE
CHANNELS = 1    # 1 = mono, 2 = stereo, and 6 = full 6 channel audio.
RATE = 16000     # 8000 (telephony), 11025, 44100 (CD),
                # 48000 (DVD audio) and 96000

CHUNK = 1024   # CHUNKS of bytes to read each time from mic
PERIOD = CHUNK # Sets the actual period size in frames. Each write should
               # consist of exactly this number of frames,
               # and each read will return this number of frames
               # (unless the device is in PCM_NONBLOCK mode, in which case it
               # may return nothing at all)

WAV_FRAME_RATE = 16000
SPEECH_THRESHOLD = 1500  # The SPEECH_THRESHOLD intensity that defines silence
                  # and noise signal (an int. lower than SPEECH_THRESHOLD is silence).

SILENCE_LIMIT = 1  # Silence limit in seconds. The max ammount of seconds where
                   # only silence is recorded. When this time passes the
                   # recording finishes and the file is delivered.

PREV_AUDIO = 0.5  # Previous audio (in seconds) to prepend. When noise
                  # is detected, how much of previously recorded audio is
                  # prepended. This helps to prevent chopping the beggining
                  # of the phrase.

RECORD_SECONDS = 3
SLEEP_TIME = 15

WAVE_OUTPUT_FILENAME = 'recording.wav'
FLAC_OUTPUT_FILENAME = 'recording.flac'

# IBM Watson credentials for STT & TTS services
IBM_USERNAME_STT = "d5b9ec82-468b-4950-81f1-3724fcbb416b"
IBM_PASSWORD_STT = "hypogOyEsjFf"
IBM_USERNAME_TTS = "7d03122a-fc83-4639-ab91-e4b9c74a4795"
IBM_PASSWORD_TTS = "2dVbmGiKLHWq"

GOOGLE_API_KEY = 'AIzaSyChAyl9GLDo4edb6N4go74DzcAwXFri8f0'
HTTP_API_URL = 'https://speech.googleapis.com/v1/speech:recognize?key={}'.format(GOOGLE_API_KEY)


def wav2flac(wav_file=WAVE_OUTPUT_FILENAME, flac_file=FLAC_OUTPUT_FILENAME):
    song = AudioSegment.from_wav(wav_file)
    song.export(flac_file, format="flac")


def audio_int_pyaudio(num_samples=NUM_OF_SAMPLES):
    """ Gets average audio intensity of your mic sound using pyaudio.
        You can use it to get average intensities while you're
        talking and/or silent.
        The average is the avg of the 20% largest intensities recorded.
    """
    print "Getting intensity values from mic."
    p = pyaudio.PyAudio()

    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK,
                    input_device_index=vID)

    values = [math.sqrt(abs(audioop.avg(stream.read(CHUNK), 4)))
              for x in range(num_samples)]
    values = sorted(values, reverse=True)
    r = sum(values[:int(num_samples * 0.2)]) / int(num_samples * 0.2)
    print " Finished "
    print " Average audio intensity is ", r
    stream.close()
    p.terminate()
    return r


def setup_pyalsa_mic():
    ''' Set up mic, capture audio, and return string of the result '''
    inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, device='pulse')
    inp.setchannels(CHANNELS)
    inp.setrate(RATE)
    inp.setformat(FORMAT_ALSA)
    inp.setperiodsize(CHUNK)
    return inp


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


def audio_int_pyalsa(num_samples=NUM_OF_SAMPLES):
    """ Gets average audio intensity of your mic sound. You can use it to get
        average intensities while you're talking and/or silent. The average
        is the avg of the 20% largest intensities recorded.
    """
    inp = setup_pyalsa_mic()
    values = [math.sqrt(abs(audioop.avg(inp.read()[1], 4)))
              for x in range(num_samples)]
    values = sorted(values, reverse=True)
    r = sum(values[:int(num_samples * 0.2)]) / int(num_samples * 0.2)
    print " Finished "
    print " Average audio intensity is ", r
    inp.close()
    return r


def listen_for_speech_pyaudio(SPEECH_THRESHOLD=SPEECH_THRESHOLD, num_phrases=-1):
    """
    Listens to Microphone with pyaudio module, extracts phrases
    from it and sends it to Google's TTS service and returns response.
    A "phrase" is sound surrounded by silence (according to SPEECH_THRESHOLD).
    'num_phrases' controls how many phrases to process before finishing
    the listening process (-1 for infinite).
    """

    # Open stream
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print "* Listening mic. "
    audio2send = []
    cur_data = ''  # current chunk  of audio data
    rel = RATE/CHUNK
    slid_win = deque(maxlen=SILENCE_LIMIT * rel)
    # Prepend audio from 0.5 seconds before noise was detected
    prev_audio = deque(maxlen=PREV_AUDIO * rel)
    started = False
    n = num_phrases
    response = []

    while (num_phrases == -1 or n > 0):
        cur_data = stream.read(CHUNK)
        slid_win.append(math.sqrt(abs(audioop.avg(cur_data, 4))))
        # print slid_win[-1]
        if(sum([x > SPEECH_THRESHOLD for x in slid_win]) > 0):
            if(not started):
                print "Starting record of phrase"
                started = True
            audio2send.append(cur_data)
        elif (started is True):
            print "Finished"
            # The limit was reached, finish capture and deliver.
            filename = save_speech(list(prev_audio) + audio2send, p)
            # Send file to Google and get response
            r = stt_google_wav(filename)
            if num_phrases == -1:
                print "Response", r
            else:
                response.append(r)

            # Remove temp file. Comment line to review.
            # os.remove(filename)

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
    stream.close()
    p.terminate()

    return response


def listen_for_speech_pyalsa(SPEECH_THRESHOLD=SPEECH_THRESHOLD, num_phrases=-1):
    """
    Listens to Microphone with pyalsa module, extracts phrases
    from it and sends it to Google's TTS service and returns response.
    A "phrase" is sound surrounded by silence (according to SPEECH_THRESHOLD).
    'num_phrases' controls how many phrases to process before finishing
    the listening process (-1 for infinite).
    """

    # Connects to pulse device 'aplay -L'
    inp = setup_pyalsa_mic()

    print "* Listening mic. "
    audio2send = []
    cur_data = ''  # current chunk  of audio data
    rel = RATE/CHUNK
    slid_win = deque(maxlen=SILENCE_LIMIT * rel)
    # Prepend audio from 0.5 seconds before noise was detected
    prev_audio = deque(maxlen=PREV_AUDIO * rel)
    started = False
    n = num_phrases
    response = []

    while (num_phrases == -1 or n > 0):
        cur_data = inp.read()[1]
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
            # r = stt_google_wav(filename)
            # if num_phrases == -1:
            #     print "Response", r
            # else:
            #     response.append(r)

            # Remove temp file. Comment line to review.
            # os.remove(filename)

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
    inp.close()

    return response


def save_speech(data, p):
    """ Saves mic data to temporary WAV file.
    Returns filename of savedfile
    """

    filename = 'output_'+str(int(time.time()))
    # writes data to WAV file
    data = ''.join(data)
    wf = wave.open(filename + '.wav', 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(WAV_FRAME_RATE)  # TODO make this value a function parameter?
    wf.writeframes(data)
    wf.close()
    return filename + '.wav'


def stt_google_wav(audio_fname):
    """ Sends audio file (audio_fname) to Google's text to speech
        service and returns service's response. We need a FLAC
        converter if audio is not FLAC (check FLAC_CONV). """

    print "Sending ", audio_fname
    #Convert to flac first
    filename = audio_fname
    del_flac = False
    if 'flac' not in filename:
        del_flac = False
        print "Converting to flac"
        print FLAC_CONV + filename
        os.system(FLAC_CONV + ' ' + filename)
        filename = filename.split('.')[0] + '.flac'

    f = open(filename, 'rb')
    flac_cont = f.read()
    f.close()

    # Headers. A common Chromium (Linux) User-Agent
    hrs = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.110 Safari/537.36",
           'Content-type': 'audio/x-flac; rate=16000'}

    req = urllib2.Request(GOOGLE_SPEECH_URL, data=flac_cont, headers=hrs)
    print "Sending request to Google TTS"
    print "response", response

    p = urllib2.urlopen(req)
    response = p.read()
    res = eval(response)['hypotheses']

    print "Couldn't parse service response"
    res = None
    print "Unexpected error:", sys.exc_info()[0]

    if del_flac:
        os.remove(filename)  # Remove temp file

    return res


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
    subprocess.call(["mplayer", audio_file_path])



if(__name__ == '__main__'):
    #listen_for_speech()  # listen to mic.
    #print stt_google_wav('output_1459452343.wav')  # translate audio file
    #audio_int_pyaudio()  # To measure your mic levels
    #audio_int_pyalsa()  # To measure your mic levels
    #TEXT = ibm_stt(10)

    #ibm_tts(TEXT)
    #play(TMP_FILE)


    listen_for_speech_pyalsa()

