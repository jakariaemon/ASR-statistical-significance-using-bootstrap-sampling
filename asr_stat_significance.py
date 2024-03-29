import random
import numpy as np
from scipy.stats import bootstrap

class StatisticalSignificance:
    """Performs statistical test between two ASR models."""
    def __init__(self, file_path, sep=",", total_batch=1000, use_gaussian_appr=False,):
        """
        Args:
            file_path (str): Path to the wer info for each test sentence
            sep (str): Separator used in file_a and file_b for error and total number of words. (default is ",")
            total_batch (int): Total amount of bootstrap sampling runs. Typical values are 10^2, 10^3, 10^4. (default is 1000)
            use_gaussian_appr (bool): Either to manually compute empirical percentiles or use gaussian approximation. (default is False)
        """
        
        self.file_path = file_path
        self.total_batch = total_batch
        
        self.data_wer = self.process_text_file(file_path, sep=sep)
        self.z_scores = {
            0.90: 1.645,
            0.95: 1.960,
            0.99: 2.576,
        }
        self.use_gaussian_appr = use_gaussian_appr 

    def cap_wer(self, errors, total_words):
        """
        Calculate WER and ensure it does not exceed 100%.
        """
        return min(errors / total_words, 1.0) if total_words > 0 else 0
    
    def process_text_file(self, file_path, sep):
        data_wer = {}
        with open(file_path, "r+") as f:
            for line in f:
                block_data = line.strip().split(sep)
                if len(block_data) >= 3:
                    edit_wer_a, edit_wer_b, num_words = map(int, block_data[:3])
                    block = block_data[3] if len(block_data) == 4 else "default"

                    # Cap the WER at 100%
                    #wer_a = self.cap_wer(edit_wer_a, num_words)
                    wer_b = self.cap_wer(edit_wer_b, num_words)

                    if block in data_wer:
                        data_wer[block].append((edit_wer_a, wer_b, num_words))
                    else:
                        data_wer[block] = [(edit_wer_a, wer_b, num_words)]

        # Convert data to NumPy arrays for easier manipulation
        for block in data_wer:
            data_wer[block] = np.array(data_wer[block])
        
        return data_wer
        
    def random_sample(self, data, num_samples,):
        """ Randomly samples from data with replacement.
        """
        
        random_index = np.random.randint(0, data.shape[0], size=num_samples)
        return data[random_index]
    
    def wer_change(self, data):
        return np.sum(data[:, 1] - data[:, 0]) / np.sum(data[:, 2])
    
    def standard_error(self, wer_change, wer_change_mean):
        std_dev = np.sum((wer_change - wer_change_mean)**2)/(len(wer_change)-1)
        return np.sqrt(std_dev)
    
    def bootstap_sampling(self, data, num_samples_per_batch):
        change_in_wer_arr = []
        for _ in range(self.total_batch):
            # sample a batch from the entire data
            sample_data = self.random_sample(data, num_samples=num_samples_per_batch,)
            
            # compute batch wer diff
            change_in_wer_batch = self.wer_change(sample_data)
            change_in_wer_arr.append(change_in_wer_batch)
            
        return np.array(change_in_wer_arr)
    
    def bootstap_sampling_block(self, data, num_samples_per_block):
        change_in_wer_arr = []
        for _ in range(self.total_batch):
            sample_data = []
            for block in data:
                block_sample_data = self.random_sample(data[block], num_samples=num_samples_per_block,)
                sample_data.append(block_sample_data)
            sample_data = np.vstack(sample_data)
            
            # compute batch wer diff
            change_in_wer_batch = self.wer_change(sample_data)
            change_in_wer_arr.append(change_in_wer_batch)
            
        return np.array(change_in_wer_arr)
    
    def compute_significance(self, num_samples_per_batch=None, num_samples_per_block=None, 
                             confidence_level=0.95, use_blockwise_bootstrap=False,):
        """
        Args:
            num_samples_per_batch (int): The number of WER/CER samples selected from the files per model
            num_samples_per_block (int): No. of wer samples to bootstrap from each block when `use_blockwise_bootstrap=True`
            confidence_level (float): Confidence level to be used for computation. Typical levels include 90%, 95% and 99% (default is 0.95)
            use_blockwise_bootstrap (bool): Perform bootstrap sampling based on blocks. (default is False)
        """
        
        assert confidence_level < 1.0, f"Sorry, confidence_level cannot be greater than 1.0 . Given confidence_level = {confidence_level}"
        if use_blockwise_bootstrap:
            assert num_samples_per_block is not None, "num_samples_per_block cannot be None when `use_blockwise_bootstrap=True`"
        else:
            assert num_samples_per_batch is not None, "num_samples_per_batch cannot be None when `use_blockwise_bootstrap=False`"
            
        if self.use_gaussian_appr:
            assert confidence_level in self.z_scores, "Sorry, only confidence levels in 0.90, 0.95 and 0.99 are supported if `self.use_gaussian_appr=True`"
            z_score = float(self.z_scores[confidence_level])
        
        data = self.data_wer
        absolute_wer_diff = None
        if use_blockwise_bootstrap:
            change_in_wer_arr = self.bootstap_sampling_block(data, num_samples_per_block)
        else:
            data_expanded = [data[block_data] for block_data in data]
            data_expanded = np.vstack(data_expanded) if len(data) > 1 else data_expanded[0]
            change_in_wer_arr = self.bootstap_sampling(data_expanded, num_samples_per_batch)
            absolute_wer_diff = self.wer_change(data_expanded)
        
        # compute standard_error
        wer_diff_bootstrap = np.mean(change_in_wer_arr)
        std_err_bootstrap = self.standard_error(change_in_wer_arr, 
                                           wer_change_mean=wer_diff_bootstrap)
        
        # compute confidence level intervals
        if self.use_gaussian_appr:
            ci_low, ci_high = wer_diff_bootstrap + z_score*std_err_bootstrap, wer_diff_bootstrap - z_score*std_err_bootstrap
        else:
            interval = (1.0 - confidence_level)/2
            ci_low, ci_high = np.percentile(change_in_wer_arr, [(1.0-interval)*100], interval*100)
        
        return WER_DiffCI(wer_diff_bootstrap, ci_low, ci_high, std_err_bootstrap, confidence_level, absolute_wer_diff)
    
class WER_DiffCI:
    def __init__(self, wer_diff_bootstrap, ci_high, ci_low, std_err, confidence_level, wer_diff_absolute=None, ):
        """
        wer_diff_bootstrap (float): The mean of the botstrap wer difference.
        ci_high (float): High value of ci on the real axis.
        ci_low (float): Low value of ci on the real axis.
        std_err (float): Standard error of the wer difference computed from the bootstrap samples.
        wer_diff_absolute (float): Absolute wer difference value computed using the mean of the wer. (default is None)
        confidence_level (float): Confidence level used to get ci_low and ci_high.
        """
        
        self.ci_low = ci_low
        self.ci_high = ci_high
        self.std_err = std_err
        self.wer_diff_bootstrap = wer_diff_bootstrap
        self.wer_diff_absolute = wer_diff_absolute
        self.confidence_level = confidence_level
    
    def is_significant(self):
        return (self.ci_low < 0) and (self.ci_high < 0)
    
    def __repr__(self):
        return f"WER_DiffCI(wer_diff_bootstrap={self.wer_diff_bootstrap}, ci_low={self.ci_low}, ci_high={self.ci_high}, std_err={self.std_err}, confidence_level={self.confidence_level})"
