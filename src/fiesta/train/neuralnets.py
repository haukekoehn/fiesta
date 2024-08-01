from typing import Sequence, Callable
import time

import jax
import jax.numpy as jnp

from jaxtyping import Array, Float

import flax
from flax import linen as nn  # Linen API
from flax.training.train_state import TrainState
from ml_collections import ConfigDict
import optax
import pickle

# from flax.training import train_state  # Useful dataclass to keep train state
# from flax import struct                # Flax dataclasses


# TODO: place the jits

###############
### CONFIGS ###
###############

class NeuralnetConfig(ConfigDict):
    """Configuration for a neural network model. For type hinting"""
    name: str = "MLP"
    layer_sizes: Sequence[int] = [64, 128, 64, 10]
    act_func: Callable = nn.relu
    optimizer: Callable = optax.adam
    learning_rate: float = 1e-3
    batch_size: int = 128
    nb_epochs: int = 1000
    nb_report: int = 100
    
    # TODO: add support for schedulers in the future
    
    # fixed_lr: bool
    # my_scheduler: ConfigDict
    # nb_epochs_decay: int
    # learning_rate_fn: Callable

    # For the scheduler:
    # config.nb_epochs_decay = int(round(config.nb_epochs / 10))
    # config.learning_rate_fn = None
    # ^ optax learning rate scheduler
    # # Custom scheduler (work in progress...)
    # config.fixed_lr = False
    # config.my_scheduler = ConfigDict() # to gather parameters
    # # In case of false fixed learning rate, will adapt lr based on following params for custom scheduler
    # config.my_scheduler.counter = 0
    # # ^ count epochs during training loop, in order to only reduce lr after x amount of steps
    # config.my_scheduler.threshold = 0.995
    # # ^ if best loss has not recently improved by this fraction, then reduce learning rate
    # config.my_scheduler.multiplier = 0.5
    # # ^ reduce lr by this factor if loss is not improving sufficiently
    # config.my_scheduler.patience = 10
    # # ^ amount of epochs to wait in loss curve before adapting lr if loss goes up
    # # config.my_scheduler.burnin = 20
    # # # ^ amount of epochs to wait at start before any adaptation is done
    # config.my_scheduler.history = 10
    # # ^ amount of epochs to "look back" in order to determine whether loss is improving or not

#####################
### ARCHITECTURES ###
#####################

class BaseNeuralnet(nn.Module):
    """Abstract base class. Needs layer sizes and activation function used"""
    layer_sizes: Sequence[int]
    act_func: Callable
    
    # def __init__(self, 
    #              layer_sizes: Sequence[int],
    #              act_func: Callable):
    #     """
    #     Initialize the neural network with the given layer sizes and activation function.

    #     Args:
    #         layer_sizes (Sequence[int]): List of integers representing the number of neurons in each layer.
    #         act_func (Callable): Activation function to be used in the network.
    #     """
        
    #     super().__init__()
    #     assert len(layer_sizes) > 1, "Need at least two layers for a neural network"
    #     self.layer_sizes = layer_sizes
    #     self.act_func = act_func

    def setup(self):
        raise NotImplementedError
    
    def __call__(self, x):
        raise NotImplementedError 
    
class MLP(BaseNeuralnet):
    """Basic multi-layer perceptron: a feedforward neural network with multiple Dense layers."""

    # def __init__(self, 
    #              layer_sizes: Sequence[int] = [64, 128, 64, 10],
    #              act_func: Callable = nn.relu):
    #     super().__init__(layer_sizes, act_func)

    def setup(self):
        self.layers = [nn.Dense(n) for n in self.layer_sizes]

    # TODO: to jit or not to jit?
    # @functools.partial(jax.jit, static_argnums=(2, 3))
    @nn.compact
    def __call__(self, x: Array):
        """_summary_

        Args:
            x (Array): Input data of the neural network.
        """

        for i, layer in enumerate(self.layers):
            # Apply the linear part of the layer's operation
            x = layer(x)
            # If not the output layer, apply the given activation function
            if i != len(self.layer_sizes) - 1:
                x = self.act_func(x)

        return x
    

# TODO: can this be removed now?
# class NeuralNetwork(nn.Module):
#     """A very basic initial neural network used for testing the basic functionalities of Flax.

#     Returns:
#         NeuralNetwork: The architecture of the neural network
#     """

#     @nn.compact
#     def __call__(self, x):
#         x = nn.Dense(features=24)(x)
#         x = nn.relu(x)
#         x = nn.Dense(features=64)(x)
#         x = nn.relu(x)
#         x = nn.Dense(features=24)(x)
#         x = nn.relu(x)
#         x = nn.Dense(features=10)(x)
#         return x


################
### TRAINING ###
################

def create_train_state(model: BaseNeuralnet, 
                       test_input: Array, 
                       rng: jax.random.PRNGKey, 
                       config: NeuralnetConfig):
    """
    Creates an initial `TrainState` from NN model and optimizer and initializes the parameters by passing dummy input.

    Args:
        model (BaseNeuralnet): Neural network model to be trained.
        test_input (Array): A test input used to initialize the parameters of the model.
        rng (jax.random.PRNGKey): Random number generator key used for initialization of the model.
        config (NeuralnetConfig): Configuration for the neural network training.

    Returns:
        TrainState: TrainState object for training
    """
    params = model.init(rng, test_input)['params']
    # TODO: this is broken
    # tx = config.optimizer(float(config.learning_rate))
    tx = optax.adam(config.learning_rate)
    state = TrainState.create(apply_fn = model.apply, params = params, tx = tx)
    return state

def apply_model(state: TrainState, 
                x_batched: Float[Array, "n_batch ndim_input"], 
                y_batched: Float[Array, "n_batch ndim_output"]):
    """
    Apply the model to a batch of data and compute the loss and gradients.

    Args:
        state (TrainState): TrainState object for training.
        x_batched (Float[Array, "n_batch ndim_input"]): Batch of input
        y_batched (Float[Array, "n_batch ndim_output"]): Batch of output
    """

    def loss_fn(params):
        def squared_error(x, y):
            # For a single datapoint
            pred = state.apply_fn({'params': params}, x)
            return jnp.inner(y - pred, y - pred) / 2.0
        # Vectorize the previous to compute the average of the loss on all samples.
        return jnp.mean(jax.vmap(squared_error)(x_batched, y_batched))

    grad_fn = jax.value_and_grad(loss_fn)
    loss, grads = grad_fn(state.params)
    return loss, grads

# TODO: what are dimensions?
@jax.jit
def train_step(state: TrainState, 
               train_X: Float[Array, "n_batch_train ndim_input"], 
               train_y: Float[Array, "n_batch_train ndim_output"], 
               val_X: Float[Array, "n_batch_val ndim_output"] = None, 
               val_y: Float[Array, "n_batch_val ndim_output"] = None) -> tuple[TrainState, Float[Array, "n_batch_train"], Float[Array, "n_batch_val"]]:
    """
    Train for a single step. Note that this function is functionally pure and hence suitable for jit.

    Args:
        state (TrainState): TrainState object
        train_X (Float[Array, "n_batch_train ndim_input"]): Training input data
        train_y (Float[Array, "n_batch_train ndim_output"]): Training output data
        val_X (Float[Array, "n_batch_val ndim_input"], optional): Validation input data. Defaults to None.
        val_y (Float[Array, "n_batch_val ndim_output"], optional): Valdiation output data. Defaults to None.

    Returns:
        tuple[TrainState, Float, Float]: TrainState with updated weights, and arrays of training and validation losses
    """

    # Compute losses
    train_loss, grads = apply_model(state, train_X, train_y)
    if val_X is not None:
        # TODO: computing the gradient here is not necessary
        val_loss, _ = apply_model(state, val_X, val_y)
    else:
        val_loss = jnp.zeros_like(train_loss)

    # Update parameters
    state = state.apply_gradients(grads=grads)

    return state, train_loss, val_loss

def train_loop(state: TrainState, 
               config: NeuralnetConfig,
               train_X: Float[Array, "ndim_input"],
               train_y: Float[Array, "ndim_output"],
               val_X: Float[Array, "ndim_input"] = None, 
               val_y: Float[Array, "ndim_output"] = None,
               verbose: bool = True):

    train_losses, val_losses = [], []

    start = time.time()
    
    for i in range(config.nb_epochs):
        # Do a single step
        
        state, train_loss, val_loss = train_step(state, train_X, train_y, val_X, val_y)
        # Save the losses
        train_losses.append(train_loss)
        val_losses.append(val_loss)
        # Report once in a while
        if i % config.nb_report == 0 and verbose:
            print(f"Train loss at step {i+1}: {train_loss}")
            print(f"Valid loss at step {i+1}: {val_loss}")
            print(f"Learning rate: {config.learning_rate}")
            print("---")

    end = time.time()
    if verbose:
        print(f"Training for {config.nb_epochs} took {end-start} seconds.")

    return state, train_losses, val_losses

def serialize(state: TrainState, 
              config: NeuralnetConfig = None) -> dict:
    """
    Serialize function to save the model and its configuration.

    Args:
        state (TrainState): The TrainState object to be serialized.
        config (NeuralnetConfig, optional): The config to be serialized. Defaults to None.

    Returns:
        _type_: _description_
    """
    
    # Get state dict, which has params
    params = flax.serialization.to_state_dict(state)["params"]
    
    # TODO: why is act func throwing errors?
    # Quick hotfix for now:
    del config["act_func"]
    
    serialized_dict = {"params": params,
                       "config": config,
                    }
    
    return serialized_dict

# TODO: add support for various activation functions and different model architectures to be loaded from serialized models
def save_model(state: TrainState, 
               config: ConfigDict = None, 
               out_name: str = "my_flax_model.pkl"):
    """
    Serialize and save the model to a file.
    
    Raises:
        ValueError: If the provided file extension is not .pkl or .pickle.

    Args:
        state (TrainState): The TrainState object to be saved.
        config (ConfigDict, optional): The config to be saved.. Defaults to None.
        out_name (str, optional): The pickle file to which we save the serialized model. Defaults to "my_flax_model.pkl".
    """
    
    if not out_name.endswith(".pkl") or not out_name.endswith(".pickle"):
        raise ValueError("For now, only .pkl or .pickle extensions are supported.")
    
    serialized_dict = serialize(state, config)
    with open(out_name, 'wb') as handle:
        pickle.dump(serialized_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
    
def load_model(filename: str) -> TrainState:
    """
    Load a model from a file.
    TODO: this is very cumbersome now and must be massively improved in the future

    Args:
        filename (str): Filename of the model to be loaded.

    Raises:
        ValueError: If there is something wrong with loading, since lots of things can go wrong here.

    Returns:
        tuple[TrainState, NeuralnetConfig]: The TrainState object loaded from the file and the NeuralnetConfig object.
    """
    
    with open(filename, 'rb') as handle:
        loaded_dict = pickle.load(handle)
        
    config: NeuralnetConfig = loaded_dict["config"]
    layer_sizes = config.layer_sizes
    # TODO: support saving and loading the activation function
    act_func = flax.linen.relu
    # act_func = config["act_func"]
    params = loaded_dict["params"]
        
    # TODO: support saving and loading different architectures
    if config.name == "MLP":
        model = MLP(layer_sizes, act_func)
    else:
        raise ValueError("Error loading model, architecture name not recognized.")
    
    # # Initialize train state
    # # TODO cumbersome way to fetch the input dimension, is there a better way? I.e. save input ndim while saving model?
    # params_keys = list(params.keys())
    # first_layer = params[params_keys[0]]
    # input_ndim = np.shape(first_layer)[0]
    
    # Create train state without optimizer
    state = TrainState.create(apply_fn = model.apply, params = params, tx = optax.adam(config.learning_rate))
    
    return state, config

# TODO: add training and loading for multiple filters

# def save_model_all_filts(svd_model: SVDTrainingModel, config: ConfigDict = None, out_name: str = "my_flax_model"):
#     # Save the learned model for all filters in SVD model
#     filters = list(svd_model.keys())
#     for filt in filters:
#         model = svd_model[filt]["model"]
#         save_model(model, config, out_name=out_name + f"_{filt}.pkl")
        
# def load_model_all_filts(svd_model: SVDTrainingModel, model_dir: str):
#     # Iterate over all the filters that are present in the SVD model
#     filters = list(svd_model.keys())
#     for filt in filters:
#         # Check whether we have a saved model for this filter
#         # TODO what if file extension changes?
#         filenames = [file for file in os.listdir(model_dir) if f"{filt}.pkl" in file]
#         if len(filenames) == 0:
#             raise ValueError(f"Error loading flax model: filter {filt} does not seem to be saved in directory {model_dir}")
#         elif len(filenames) > 1:
#             print(f"Warning: there are several matches with filter {filt} in directory {model_dir}, loading first")
#         # If we have a saved model, load in and save into our object
#         filename = filenames[0]
#         state = load_model(model_dir + filename)
#         svd_model[filt]["model"] = state