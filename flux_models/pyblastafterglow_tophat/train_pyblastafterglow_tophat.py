import numpy as np 
import matplotlib.pyplot as plt
import h5py

from fiesta.train.FluxTrainer import PCATrainer
from fiesta.inference.lightcurve_model import AfterglowFlux
from fiesta.train.neuralnets import NeuralnetConfig

#############
### SETUP ###
#############

tmin = 0.1 # days
tmax = 2000


numin = 1e9 # Hz 
numax = 2.5e18

n_training = 57_600
n_val = 5760
n_pca = 200

name = "tophat"
outdir = f"./model/"
file = outdir + "pyblastafterglow_raw_data.h5"

config = NeuralnetConfig(output_size=n_pca,
                         nb_epochs=300_000,
                         hidden_layer_sizes = [300, 600, 300],
                         learning_rate =3e-3)

###############
### TRAINER ###
###############


data_manager_args = dict(file = file,
                           n_training= n_training,
                           n_val= n_val, 
                           tmin= tmin,
                           tmax= tmax,
                           numin = numin,
                           numax = numax,
                           special_training=[])

trainer = PCATrainer(name,
                     outdir,
                     data_manager_args = data_manager_args,
                     plots_dir=f"./benchmarks/",
                     n_pca = n_pca,
                     save_preprocessed_data=False
                     )

###############
### FITTING ###
###############

trainer.fit(config=config)
trainer.save()

#############
### TEST ###
#############

print("Producing example lightcurve . . .")
FILTERS = ["radio-3GHz", "X-ray-1keV", "radio-6GHz", "bessellv"]

lc_model = AfterglowFlux(name,
                          outdir, 
                          filters = FILTERS,
                          model_type = "MLP")


with h5py.File(file, "r") as f:
    X_example = f["val"]["X"][-1]
    y_raw = f["val"]["y"][-1, trainer.data_manager.mask]
    y_raw = y_raw.reshape(len(lc_model.nus), len(lc_model.times))
    mJys = np.exp(y_raw)

    # Turn into a dict: this is how the model expects the input
    X_example = {k: v for k, v in zip(lc_model.parameter_names, X_example)}
    
    # Get the prediction lightcurve
    y_predict = lc_model.predict(X_example)

    
    for filt in lc_model.Filters:

        y_val = filt.get_mag(mJys, lc_model.nus)

        plt.plot(lc_model.times, y_val, color = "red", label="pyblastafterglow")
        plt.plot(lc_model.times, y_predict[filt.name], color = "blue", label="Surrogate prediction")
        upper_bound = y_predict[filt.name] + 1
        lower_bound = y_predict[filt.name] - 1
        plt.fill_between(lc_model.times, lower_bound, upper_bound, color='blue', alpha=0.2)
    
        plt.ylabel(f"mag for {filt.name}")
        plt.xlabel("$t$ in days")
        plt.legend()
        plt.gca().invert_yaxis()
        plt.xscale('log')
        plt.xlim(lc_model.times[0], lc_model.times[-1])
    
        plt.savefig(f"./benchmarks/pyblastafterglow_{name}_{filt.name}_example.png")
        plt.close()