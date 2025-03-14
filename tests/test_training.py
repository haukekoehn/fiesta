import os
from pathlib import Path

from fiesta.train.FluxTrainer import PCATrainer
from fiesta.train.neuralnets import NeuralnetConfig


#############
### SETUP ###
#############

tmin = 1 # days
tmax = 100

numin = 3e9 # Hz 
numax = 1e15

n_training = 200
n_val = 20
n_pca = 10

working_dir = os.path.dirname(__file__)
file = os.path.join(working_dir, "data/test_raw_data.h5")


config = NeuralnetConfig(output_size=n_pca,
                         nb_epochs=10,
                         hidden_layer_sizes = [10],
                         learning_rate =1e-3)


###############
### TRAINER ###
###############


data_manager_args =   dict(file=file,
                           n_training=n_training,
                           n_val=n_val, 
                           tmin=tmin,
                           tmax=tmax,
                           numin=numin,
                           numax=numax,
                           special_training=["01"])




def test_train_and_save():

    name = "tophat"

    trainer = PCATrainer(name,
                     working_dir,
                     data_manager_args = data_manager_args,
                     n_pca = n_pca,
                     save_preprocessed_data=False
                     )

    trainer.fit(config=config)
    trainer.save()

    for file in Path(working_dir).glob("*.pkl"):
        file.unlink() # Deletes the files