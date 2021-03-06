from termcolor import colored
print(colored('Loading libraries...', attrs=['bold']))
import os
import sys
import math
print(colored('Loading numpy...', attrs=['bold']))
import numpy as np
print(colored('Loading tqdm...', attrs=['bold']))
from tqdm import tqdm, trange
sys.path.append('./source/network')
print(colored('Loading datasync...', attrs=['bold']))
from Dataloader import datasync as sync
from Dataloader import loader
print(colored('Loading tensorflow...', attrs=['bold']))
import tensorflow as tf
print(colored('Loading keras...', attrs=['bold']))
import keras
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, LSTM, BatchNormalization, Bidirectional, TimeDistributed, Conv1D, MaxPooling1D, Flatten, InputLayer, Input
import keras.backend as K
from keras.optimizers import Adam, SGD, RMSprop, Adagrad
from tensorflow.python.client import device_lib
print(colored('Loading matplotlib...', attrs=['bold']))
import matplotlib.pyplot as plt
from functools import reduce
from time import sleep
import time
from tensorflow.python.client import device_lib
print(colored('Loading pytorch...', attrs=['bold']))
import torch

# set memory growth
print(colored('Configuring GPU...', 'yellow', attrs=['bold']))
for gpu in tf.config.experimental.list_physical_devices('GPU'):
    tf.config.experimental.set_memory_growth(gpu, True)

# PATH DEFINITIONS
absolute_path = os.path.join('/home/lemonorange/catRemixV2')
data_root_path = os.path.join(absolute_path, 'data')
input_path = os.path.join(data_root_path, 'wav')
label_data_path = os.path.join(data_root_path, 'rawMid')
print(colored('\n==================== TRAIN START ====================\n', 'grey', 'on_yellow'))
print('Attempting to opening dataset paths...')
if(not os.path.exists(input_path)):
    raise FileNotFoundError('Input path does not exist! Are you sure all of the data are generated?') # check if path exists
if(not os.path.exists(label_data_path)):
    raise FileNotFoundError('Label path does not exist! Are you sure all of the data are generated?') # check if path exists

# DATA PARTITIONS
training_files = []
validation_files = []

# DATA PARTITIONING
val_perc=0.005 # partitioning parameters

print('Attempting to partition data...')
all_files = os.listdir(input_path)
data_size = len(all_files)
# partition validation files
validation_files = np.array(all_files[0 : int( data_size * val_perc )])
all_files = all_files[int( data_size * val_perc ) :] # trim original files
# partition the rest into training files
training_files = np.array(all_files[:])

validation_file_size = validation_files.shape[0] # size of validation
training_file_size = training_files.shape[0] # size of training

# DATA PARTITIONING Finished
print(colored('Data partitioned successfully!', 'green'))
print(colored('  |__ {validation_file_size} validation data points'.format(**locals()), 'green'))
print(colored('  |__ {training_file_size} training data points\n'.format(**locals()), 'green'))

# DATA details
# chunk_length_seconds = 0.125 # DEPRECATED
sample_rate = 44000
# sample_per_chunk = int(sample_rate * chunk_length_seconds) # DEPRECATED
n_batch = 30 # the amount of batches needed, in this case, N file per batch
save_interval = 400 # save an instance every X min-batch (makeshift early stopping)
epochs = 1
data_cut_off = training_file_size # how much files are gonna be processed, with training_file_size being the maximum

# ==================== NETWORK DEFINITIONS ====================
def make_model(mel_res):
    model = Sequential()
    # extract features and dropout
    model.add(TimeDistributed(
        Conv1D(64, 3, activation='relu'),
            batch_input_shape=(None, None, mel_res, 1) # batch_size, window size, mel res, channel
        )
    )
    model.add(TimeDistributed(MaxPooling1D(2, strides=2)))

    model.add(TimeDistributed(Conv1D(128, 4, activation='relu')))
    # model.add(TimeDistributed(MaxPooling1D(2, strides=2)))

    # model.add(TimeDistributed(Conv1D(256, 4, activation='relu')))
    # model.add(TimeDistributed(MaxPooling1D(2, strides=2)))

    # flatten feature per time step w/ dropout
    model.add(TimeDistributed(BatchNormalization()))
    model.add(TimeDistributed(Flatten()))

    # this creates a time distributed input to the LSTM
    # input to BLSTM (this will be a 2 BLSTM layer model)
    model.add(
        Bidirectional(
            LSTM(500, return_sequences=True, activation='relu'),
            merge_mode='sum'
        )
    )

    model.add(
        Bidirectional(
            LSTM(400, return_sequences=True, activation='relu'),
            merge_mode='sum'
        )
    )

    model.add(
        Bidirectional(
            LSTM(200, return_sequences=False, activation='relu'),
            merge_mode='sum'
        )
    )

    model.add(BatchNormalization())

    # classifier with sigmoid activation for multilabel
    model.add(Dense(120, activation='relu'))
    model.add(Dense(90, activation='relu'))
    model.add(Dense(88, activation='sigmoid'))
    return model

# ==================== LOSS & OPTIMIZER DEFINITIONS ====================
loss_list = [
    tf.losses.binary_crossentropy,
    tf.losses.categorical_crossentropy,
    tf.losses.mean_squared_error,
    tf.losses.mean_absolute_error,
    tf.nn.sigmoid_cross_entropy_with_logits,
]
loss_label = [ # how the loss functions will be named when displayed on a graph
    'Binary_CSE',
    'Categorical_CSE',
    'Mean_Squared_Error',
    'Mean_Absolute_Error',
    'Sigmoid_CSE_with_Logits',
]
default_loss_index = 0 # loss selection (0 means using the first loss function, 1 the second one, and so on).

# create optimizer
default_opt = Adam(learning_rate=1e-3)

# input parameters
mel_res = 512
window_size = 4096
hop_len = 1024

# ==================== RECORDING PROCESS ====================
def write_loss(losses, labels, fout): # create loss recording function
    i = 0
    write_out = ''
    for loss in losses:
        line = str(np.mean(loss.numpy().tolist()))
        write_out += labels[i]+'='
        write_out += line if line != 'nan' else '-1'
        write_out += ';'
        i+=1
    write_out += '\n'
    foutf = open(fout, 'a')
    foutf.write(write_out)
    foutf.close()

# ==================== TRAINING PROCESS ====================
# training input and label should be synchronized and encoded (label in onehot)!!!
def train_step(input, label, model, train_fout=None, val_fout=None):
    # {X}_fout is there for if we want to record the loss data

    # get a validation input
    validation_input_name = np.random.choice(validation_files)
    # parse the validation set
    validation_input, val_sr = loader.parse_input(validation_input_name, input_path) # get input data and sample rate
    validation_label, val_bpm = loader.parse_label(validation_input_name, label_data_path) # get label data and bpm

    # generate mel spectrogram
    val_ml = loader.get_mel_spec(validation_input, mel_res, val_sr, window_size, hop_len)

    # trim the label data
    validation_label = sync.trim_front(validation_label)

    val_input, val_label = sync.sync_data(val_ml, validation_label, val_bpm, hop_len)
    val_label = np.array(loader.encode_multihot(val_label)) # encode to multi-hot

    val_input = np.reshape(val_input, (val_input.shape[0], val_input.shape[1], val_input.shape[2], 1))
    # reshape to a tensor which the neural net can use (mini_batch_size, window_size, mel_resolution, channel)

    with tf.GradientTape() as tape: # Start calculating the gradient and applying it
        # generate the predictions
        # it is garenteed the ground truth and prediction will have the same shape
        training_prediction = [] # crate temporary array of predictions so we can concat them later for mini-batch processing
        for sample in input:
            temp_pred = model(sample) # get a training pred
            training_prediction.append(temp_pred)
        # concatinate the perdictions
        training_prediction = tf.concat(training_prediction, 0)
        validation_prediction = model(val_input) # get a validation pred

        training_losses = [x(label, training_prediction) for x in loss_list] # store all training losses
        validation_losses = [x(val_label, validation_prediction) for x in loss_list] # store all validation losses
        applicable_loss = training_losses[default_loss_index] # idk why i named it this but this is the training loss
        visible_loss = validation_losses[default_loss_index] # validation loss

        # store loss
        if(train_fout != None):
            write_loss(training_losses, loss_label, train_fout)
        if(val_fout != None):
            write_loss(validation_losses, loss_label, val_fout)

        # calculate and apply gradient
        grad = tape.gradient(applicable_loss, model.trainable_variables)
        # THIS SHIT DOESNT WORK AND IDK WHY
        default_opt.apply_gradients(zip(grad, model.trainable_variables))

        overall_train_loss = np.mean(applicable_loss)
        overall_val_loss = np.mean(visible_loss)
        # CLI debug messages
        # print(colored('>>> Overall Training Loss: ', 'green') + colored(str(overall_train_loss), 'green', attrs=['bold', 'reverse']))
        # print(colored('>>> Overall Validation Loss: ', 'green') + colored(str(overall_val_loss), 'green', attrs=['bold', 'reverse']))

        return overall_train_loss, overall_val_loss

#  start training process
# training data storages
network_write_path = os.path.join(absolute_path, 'network', 'latest-cycle')
# if it doesn't exist, create one
try:
    os.makedirs(network_write_path) # if it doesn't exist, create on
except FileExistsError:
    pass # if it already exist, keep it that way

train_loss_tracking = os.path.join(network_write_path, 'train_loss.txt')
val_loss_tracking = os.path.join(network_write_path, 'val_loss.txt')

print(colored('>>> Attempting to create neural network...', 'yellow'))

# initialize model and training processes
model = make_model(mel_res) # create a new model instance
print(colored('Compiling network...', 'yellow'))
model.compile()

print(colored('Compilation successful; Architecture summary:', 'green'))
model.summary()

print(colored('\n>>> Performing preflight check... \n', 'green', attrs=['bold']))
print(colored('Detected devices:', 'green'))
print(device_lib.list_local_devices())
if(torch.cuda.is_available()):
    print(colored('CUDA capable device found:', 'green'))
    name = torch.cuda.get_device_name()
    print(colored('\t|_ Name: {name}'.format(**locals()), 'white', attrs=['bold']))
    cap = torch.cuda.get_device_capability()
    print(colored('\t|_ Compute Capability: {cap}'.format(**locals()), 'white', attrs=['bold']))
    vram = torch.cuda.get_device_properties(0).total_memory
    print(colored('\t|_ VRAM Size: {vram}MB'.format(**locals()), 'white', attrs=['bold']))
else:
    print(colored('CUDA capable device not found. Using CPU instead', 'red'))

# bruh  = tqdm(range(100), bar_format='{l_bar}{bar:10}{r_bar}{bar:-10b}')
# for i in bruh:
#     bruh.set_description('Training on ' + colored(str(i), 'grey', 'on_yellow'))
#     systemclock.sleep(0.2)
#     pass

print(colored('\n>>> Training...\n', 'green', attrs=['bold']))

# temp_input = []
# temp_out = []
#
# for i in training_files[:n_batch]:
#     unpaired_input = loader.parse_input(i, input_path) # parse input
#     unpaired_ground_truth = sync.trim_front(loader.parse_label(i, label_data_path)) # parse output
#     input, ground_truth = sync.sync_data(unpaired_input, unpaired_ground_truth, len(unpaired_ground_truth)) # pair IO + trim
#     ground_truth = np.array(loader.encode_multihot(ground_truth))
#
#     input = np.array(input)
#     input = np.reshape(input, (input.shape[0], 1, input.shape[1])) # reshape to a tensor which the neural net can use
#
#     temp_input.append(input)
#     temp_out.append(ground_truth)
#
# a = np.concatenate(temp_input)
# b = np.concatenate(temp_out)
# a.shape
# b.shape
#
# train_loss, val_loss = train_step(a, b, model, train_fout=train_loss_tracking, val_fout=val_loss_tracking)
# train_loss
# val_loss
#
# logits = model(a)
#
# logits.numpy().shape
#
# loss_list[default_loss_index](b, logits).numpy().shape

for i in range(1,epochs+1):
    # display epoch progression
    print(colored('\n\t- Epochs {i}/{epochs}'.format(**locals()), 'cyan'))

    # for every epoch, shuffle the data
    np.random.shuffle(training_files)

    # create tqdm display bar, as well as the loop itself, all looped by indexes
    file_range = tqdm(range(0, data_cut_off, n_batch), bar_format='{l_bar}{bar:20}{r_bar}{bar:-20b}', leave=True)
    # main display
    file_range.set_description(colored('Initializing...', 'grey', 'on_yellow'))
    train_loss = 'n/a'
    val_loss = 'n/a'
    on_batch = 0

    # loop through data with n_batch per mini-batch until file_range ends
    for j in file_range: # train with data index
        # parse mini_batch IO
        X = []
        temp_out = []
        # ===== READING IN TRAINING FILES =====
        for file in (training_files[j : j+n_batch]): # loop through current mini-batch
            # set loop header to reading file state
            header = colored('Reading and processing file: [{file}]...'.format(**locals()), 'grey', 'on_yellow') +'          | ' + colored('Last Trn Loss: ', 'green') + colored(str(train_loss), 'green', attrs=['bold', 'reverse']) + '; ' + colored('Last Val Loss: ', 'green') + colored(str(val_loss),'green', attrs=['bold', 'reverse'])
            file_range.set_description(header)
            file_range.refresh()

            unpaired_input, sr = loader.parse_input(file, input_path) # parse input
            if(unpaired_input.size == 0):
                print(colored('skipped {file}'.format(**locals()), 'red'))
                continue
            # create mel spectrogram
            unpaired_input_ml = loader.get_mel_spec(unpaired_input, mel_res, sr, window_size, hop_len)
            # get label for input
            unpaired_label, bpm = loader.parse_label(file, label_data_path)
            unpaired_label = sync.trim_front(unpaired_label) # trimming the MIDI and syncying the data

            input, label = sync.sync_data(unpaired_input_ml, unpaired_label, bpm, hop_len) # pair IO
            # 7480_4 cocks it up
            label = np.array(loader.encode_multihot(label)) # encode label

            input = np.reshape(input, (input.shape[0], input.shape[1], input.shape[2], 1)) # reshape to a tensor which the neural net can use

            X.append(input) # add to stash
            temp_out.append(label) # add to stash

        y = np.concatenate(temp_out)

        # TODO: implement make shift early stopping system

        # actual training part
        # STEP 1: Update status bar
        header = colored('Training On Network...', 'grey', 'on_yellow') +'   | ' + colored('Last Trn Loss: ', 'green') + colored(str(train_loss), 'green', attrs=['bold', 'reverse']) + '; ' + colored('Last Val Loss: ', 'green') + colored(str(val_loss),'green', attrs=['bold', 'reverse'])
        file_range.set_description(header)
        file_range.refresh()

        # STEP 2: calculate train step
        train_loss, val_loss = train_step(X, y, model, train_fout=train_loss_tracking, val_fout=val_loss_tracking)
        # STEP 3: update losses (round to 4th decimal point)
        train_loss = int(train_loss * 10000) / 10000
        val_loss = int(val_loss * 10000) / 10000

        # STEP 4: save snapshot if necessary
        if(on_batch%save_interval == 0):
            batch_num = j//n_batch
            model.save(os.path.join(network_write_path, 'snp_{i}_{batch_num}.h5'.format(**locals())))
        on_batch += 1

# close loss tracker, assuming program terminated correctly
model.save(os.path.join(network_write_path, 'snp_fin.h5'))

# THESE CODE ARE FOR TESTING PURPOSES ONLY.
# test_in = loader.parse_input(training_files[100], input_path)
# test_gt = sync.trim_front(loader.parse_label(training_files[100], label_data_path))
# train_set, label_set = sync.sync_data(test_in, test_gt, len(test_gt))
#
# validation_input_name = np.random.choice(validation_files)
# # parse the validation set
# validation_input = loader.parse_input(validation_input_name, input_path)
# validation_label = sync.trim_front(loader.parse_label(validation_input_name, label_data_path))
# val_input, val_label = sync.sync_data(validation_input, validation_label, len(validation_label))
# val_label = loader.encode_multihot(val_label) # encode to multi-hot
#
# training_losses = [x(val_label, [np.zeros(88, dtype=np.float32)]*13) for x in loss_list]
