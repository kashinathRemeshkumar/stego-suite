Usage

cover.audio_file= the carrier file to which the secret audio is going to be encoder need to have longer runtime that secret.audio_file
secret.audio_file= the secret msg that need to be hidden

encode:
python cli.py embed cover.mp3 secret.mp3 stego.wav --bits 4

here bits imply the number of bits used in the carrier to hide the secret higher bits lead to poor cover but better recovery

decode
python cli.py extract stego.wav recovered_secret.wav


Limitations

the encoding is a tradeoff between cover quality and secret quality increase --bits to 6 for better recoverability
but this may cause the cover to be distorted. 
The recovery is not lossless some distortion is there even when using 8 bits 

a sample audio has be included which was encoded using the following command

pyenv python cli.py embed cover.mp3 secret.mp3 stego.wav --bits 6
