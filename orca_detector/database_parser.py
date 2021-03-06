# -*- coding: future_fstrings -*-

"""
File to parse and label datafiles for the Orca project.

W251 (Summer 2019) - Spyros Garyfallos, Ram Iyer, Mike Winton
"""

import click
import numpy as np
import mel_params
import orca_params
import orca_utils
import os
import pandas as pd
import pickle
import pprint
import random
import re
import resampy
import soundfile as sf

from collections import defaultdict
from mel_features import frame, log_mel_spectrogram
from sklearn.preprocessing import LabelEncoder

# Set a seed so we get consistent results
np.random.seed(251)

def label_files(data_path=orca_params.DATA_PATH):
    """
        Walks the data_path looking for *.wav files and builds a dictionary of files and their
        respective labels based on subdirectory names.

        ARGS:
            data_path = directory root to walk

        RETURNS:
            dictionary with key=label name; value=list of associated files
    """

    # build a defaultdict of all of the samples read from disk.
    # key will be the class label (text). Value will be a list of all file paths
    total_files = 0
    all_samples = defaultdict(list)
    for (dirpath, dirnames, filenames) in os.walk(data_path):
        # extract audio filenames
        filenames = [filename for filename in filenames if os.path.splitext(filename)[
            1].lower() == '.wav']
        total_files += len(filenames)
        if len(filenames) == 0:
            continue  # try next folder

        # extract folder names as labels from a path that looks like:
        #   /data/MarineMammalName/1975 or
        #   /data/Noise/BushPoint
        path, year_folder = os.path.split(dirpath)
        _, label = os.path.split(path)
        # strip non alphanumeric characters
        label = re.sub('\W+', '', label)

        all_samples[label].extend(
            [os.path.join(dirpath, file) for file in filenames])
        # print('Loaded data from {}, mapped to label={}'.format(dirpath, label))

    print(f'''In walking directory, 
        observed {len(all_samples)} labels for {total_files} audio files.''')
    return all_samples


def _backup_datafile(file_path, suffix='-old'):
    """
        Rename file_path to file_path+suffix to provide one level of "undo".

        ARGS:
            file_path = path of file to be renamed
            suffix = string to append during renaming

        RETURNS:
            nothing
    """

    if os.path.exists(file_path):
        renamed_file = '{}{}'.format(file_path, suffix)
        os.rename(file_path, renamed_file)
        print('Renamed {} to {}'.format(file_path, renamed_file))


def _quantize_sample(label,
                     file,
                     sample_len=orca_params.FILE_SAMPLING_SIZE_SECONDS,
                     max_len=orca_params.FILE_MAX_SIZE_SECONDS):
    """
        Splits up a given file into non-overlapping segments of the specified length.
        Returns a list containing (label, 'file:start:frames') of each segment.

        Final trailing segments that are too short are dropped.

        ARGS:
            label = string name
            file = *.wav audio file
            sample_length = length of audio segments to be identified
            max_len = the maximum acceptable input length to quantize

        RETURNS:
            list of audio segments
    """

    with sf.SoundFile(file) as wav_file:
        # make sure sample is long enough
        min_frames = int(sample_len * wav_file.samplerate)  # e.g. 2 * 16000
        # TODO: Drop the long samples
        if wav_file.frames > min_frames:
            file_parts = np.arange(0, wav_file.frames, min_frames)
            sample_list = [[label, '{}:{}:{}'.format(
                file, int(start), min_frames)] for start in file_parts]

            # truncate final sample which will be shorter than min required for a spectrogram
            del sample_list[-1]
            return sample_list
        else:
            return []


def _quantize_samples(samples):
    """
        Quantizes a list of audio files into short segments

        ARGS:
            samples = list of (label, file path)

        RETURNS:
            flattened list
    """
    quantized_samples = [_quantize_sample(label, file) for [
        label, file] in samples]
    flat_quantized_samples = [
        item for sublist in quantized_samples for item in sublist]
    return flat_quantized_samples


def _flatten_and_quantize_dataset(dataset):
    """
        Flattens and quantizes audio segments from each file in the dataset (train/val/test)

        ARGS:
            dataset = list of (label, file path)

        RETURNS:
            flattened list of audio segments from the specified files
    """

    # Create lists with each element looking like:
    #   ['SpermWhale', '/data/SpermWhale/1985/8500901B.wav']
    dataset_flattened = [[label, file]
                         for label in dataset.keys() for file in dataset[label]]
    dataset_quantized = _quantize_samples(dataset_flattened)
    print('\nQuantized {} audio segments from {} sample files.'
          .format(len(dataset_quantized), len(dataset_flattened)))

    return dataset_quantized


def encode_labels(labels, encoder):
    """
        One-hot encodes labels in preparation for passing to a Keras model.

        ARGS:
            labels = list of all observed label names (may be a tuple)
            encoder = the fitted LabelEncoder to use

        RETURNS:
            np.array[observations, classes] representing the labels
    """

    encoded_labels = encoder.transform(labels)

    # build into a numpy array to return
    onehot_encoded_labels = np.zeros(
        (len(encoded_labels), len(encoder.classes_)))
    onehot_encoded_labels[np.arange(len(encoded_labels)), encoded_labels] = 1
    return onehot_encoded_labels


def _waveform_to_mel_spectrogram_segments(data, sample_rate):
    """
    Converts audio from a single wav file into an array of examples for VGGish.

    Args:
        data: np.array of either one dimension (mono) or two dimensions
          (multi-channel, with the outer dimension representing channels).
          Each sample is generally expected to lie in the range [-1.0, +1.0],
          although this is not required. Shape is (num_frame, )
        sample_rate: Sample rate of data.

    Returns:
        3-D np.array of shape [num_examples, num_frames, num_bands] which represents
        a sequence of examples, each of which contains a patch of log mel
        spectrogram, covering num_frames frames of audio and num_bands mel frequency
        bands, where the frame length is mel_params.STFT_HOP_LENGTH_SECONDS.

    IMPORTANT: if data.shape < (80000, ) then log_mel_examples.shape=(0, 496, 64).
        The zero is problematic downstream, so code will have to check for that.
    """

    # Convert to mono if necessary.
    if len(data.shape) > 1:
        #print(f'DEBUG: audio channels before={data.shape}')
        data = np.mean(data, axis=1)
        #print(f'DEBUG: audio channels after={data.shape}')

    # Resample to the rate assumed by VGGish.
    if sample_rate != mel_params.SAMPLE_RATE:
        data = resampy.resample(data, sample_rate, mel_params.SAMPLE_RATE)

    # Compute log mel spectrogram features.
    log_mel = log_mel_spectrogram(data,
                                  audio_sample_rate=mel_params.SAMPLE_RATE,
                                  log_offset=mel_params.LOG_OFFSET,
                                  window_length_secs=mel_params.STFT_WINDOW_LENGTH_SECONDS,
                                  hop_length_secs=mel_params.STFT_HOP_LENGTH_SECONDS,
                                  num_mel_bins=mel_params.NUM_MEL_BINS,
                                  lower_edge_hertz=mel_params.MEL_MIN_HZ,
                                  upper_edge_hertz=mel_params.MEL_MAX_HZ)

    # Frame features into examples.
    features_sample_rate = 1.0 / mel_params.STFT_HOP_LENGTH_SECONDS
    example_window_length = int(
        round(mel_params.EXAMPLE_WINDOW_SECONDS * features_sample_rate))
    example_hop_length = int(
        round(mel_params.EXAMPLE_HOP_SECONDS * features_sample_rate))

    # If log_mel.shape[0] < mel_params.NUM_FRAMES, log_mel_examples will return
    #   an array with log_mel_examples.shape[0] = 0
    log_mel_examples = frame(log_mel,
                             window_length=example_window_length,
                             hop_length=example_hop_length)

    # print(f'DEBUG: data.shape={data.shape}')
    # print(f'DEBUG: log_mel_examples.shape={log_mel_examples.shape}')
    if log_mel_examples.shape[0] == 0:
        print('\nWARNING: audio sample too short! Using all zeros for that example.\n')
    return log_mel_examples


def extract_segment_features(segment):
    """
        Generates the features for the given audio sample segment.

        Return format is based on pretrained Keras VGGish model input shape.

        Returns X : np.array (num_samples, num_frames, num_bands, 1)
    """

    X = np.zeros((1, mel_params.NUM_FRAMES,
                  mel_params.NUM_BANDS, 1))

    # Generate data from the appropriate segment of the audio file
    data, sample_rate = sf.read(segment.split(':')[0],
                                start=int(segment.split(':')[1]),
                                frames=int(segment.split(':')[2]))
    # Transform to log mel spectrogram format and store sample
    spectrogram = _waveform_to_mel_spectrogram_segments(
        data, sample_rate)
    spectrogram = np.expand_dims(spectrogram, 3)

    # anticipate case where sound sample was too small to create the spectrogram
    if spectrogram.shape[0] > 0:
        X[0, :, :, :] = spectrogram

    return X


def _extract_and_save_features(dataset,
                               data_path,
                               dataset_type=None,
                               backup=True):
    """
        Extracts the features (melspectrogram) of the flattened dataset 
        and saves extracted features in the specified pickle file
    """

    # check if the dataset_type is valid
    if dataset_type not in [item.value for item in orca_params.DatasetType]:
        raise ValueError('ERROR: invalid DatasetType specified.')
    print('Extracting features from {} segments for {} dataset.'.format(
        (len(dataset)), (dataset_type.name)))

    filename = os.path.join(data_path, dataset_type.name+'.features')
    if os.path.exists(filename):
        os.remove(filename)
    data = []
    for index, segment in enumerate(dataset):
        # display progress udpates
        if index % 500 == 0:
            print(f'{100*index/len(dataset):.2f}%')
        features = extract_segment_features(segment[1])
        data.append([segment[0], features])

    _backup_datafile(filename)
    with open(filename, 'wb') as fp:
        pickle.dump(data, fp)

    print(f'Saved features of dataset {dataset_type.name}')




def load_features(data_path=orca_params.DATA_PATH,
                  dataset_type=None,
                  remove_classes=orca_params.REMOVE_CLASSES,
                  other_classes=orca_params.OTHER_CLASSES):
    """
        Loads the features datasets from the file system.

        Returns [features, labels] : [num_samples(num_samples), np.array (num_samples, num_frames, num_bands, 1)]
    """

    if dataset_type not in orca_params.DatasetType:
        raise ValueError('ERROR: invalid DatasetType specified.')
    features_file = os.path.join(data_path, dataset_type.name+'.features')

    if os.path.exists(features_file):
        with open(features_file, 'rb') as f:
            features = pickle.load(f)
        print('\nLoaded {} dataset from {}'.format(
            dataset_type.name, features_file))
    else:
        raise Exception(
            'ERROR: run database_parser.py to generate datafiles first.')

    #remove classes
    features = [item for item in features if item[0] not in remove_classes]
    
    #rename classes
    for item in features:
        if item[0] in other_classes: 
            item[0] = orca_params.OTHER_CLASS

    labels, features = zip(*features)

    features = np.array(features)
    labels = np.array(labels)

    # We need to remove one empty dimension
    features = features[:, 0, :, :, :]

    return features, labels


def create_label_encoding(classes,
                          data_path=orca_params.OUTPUT_PATH,
                          save=True,
                          run_timestamp='unspecified'):
    """
        Saves LabelEncoder so inverse transforms can be recovered

        Returns encoder : LabelEncoder
    """

    encoder = LabelEncoder()
    encoder.fit(classes)
    if save:
        label_encoder_filename = f'label_encoder_{run_timestamp}.p'
        label_encoder_path = os.path.join(data_path, label_encoder_filename)
        with open(label_encoder_path, 'wb') as fp:
            pickle.dump(encoder, fp)
            print('Saved label encoder to {}'.format(label_encoder_path))

        symlink_path = os.path.join(data_path, 'label_encoder_latest.p')
        orca_utils.create_or_replace_symlink(label_encoder_path, symlink_path)
        print(f'Created symbolic link to encoder as {symlink_path}')

        # Also save human-readable version
        label_encoder_filename = f'label_encoder_{run_timestamp}.csv'
        csv_path = os.path.join(data_path, label_encoder_filename)
        df = pd.DataFrame(list(enumerate(encoder.classes_)), columns=['encoded_id', 'label'])
        df.to_csv(csv_path, index=False)
        print('Saved label encoder (in csv format) to {}'.format(csv_path))

        symlink_path = os.path.join(data_path, 'label_encoder_latest.csv')
        orca_utils.create_or_replace_symlink(csv_path, symlink_path)
        print(f'Created symbolic link to encoder csv as {symlink_path}')

    return encoder

    
@click.command(help="Indexes files and creates a train/val/test split.",
               epilog=orca_params.EPILOGUE)
@click.option('--overwrite',
              help='Regenerate features, overwriting any existing feature files.',
              default=False,
              is_flag=True,
              show_default=False)
def read_files_and_extract_features(overwrite, 
                                    data_path=orca_params.DATA_PATH,
                                    train_percentage=.70,
                                    validate_percentage=0.20):
    """
        Index files and create a train/val/test split.  Note that label one-hot
        encoding is *not* done at this point, nor are undesired classes converted
        to "Other".  That is done when loading the dataset.
    """

    if not overwrite:
        # check if all of the features files exist, and if so return.
        files_exist = True
        for d in orca_params.DatasetType:
            if not os.path.exists(os.path.join(data_path, d.name+'.features')):
                files_exist = False
                break
        if files_exist:
            return
        
    all_samples = label_files(data_path=orca_params.DATA_PATH)

    datasets = {orca_params.DatasetType.TRAIN: defaultdict(list),
                orca_params.DatasetType.VALIDATE: defaultdict(list),
                orca_params.DatasetType.TEST: defaultdict(list)}

    # do a stratified train/val/test split
    for label, files in all_samples.items():
        if len(files) < 10:
            continue  # don't bother to shuffle
        random.shuffle(files)
        num_train_files = int((len(files) + 1) * train_percentage)
        num_validate_files = int((len(files) + 1) * validate_percentage)
        datasets[orca_params.DatasetType.TRAIN][label] = \
            files[: num_train_files]
        datasets[orca_params.DatasetType.VALIDATE][label] = \
            files[num_train_files: num_train_files + num_validate_files]
        datasets[orca_params.DatasetType.TEST][label] = \
            files[num_train_files + num_validate_files:]

    # quantize and flatten each dataset
    for dataset_type, contents in datasets.items():
        flattened_dataset = _flatten_and_quantize_dataset(contents)
        _extract_and_save_features(flattened_dataset,
                                   data_path,
                                   dataset_type)
    print('Done extracting features!')
    
