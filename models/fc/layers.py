import numpy as np
import torch
from torch import nn
from models.utils import modules
from models.fc import excitability_modules as em


class fc_layer(nn.Module):
    '''Fully connected layer, with possibility of returning "pre-activations".

    Input:  [batch_size] x ... x [in_size] tensor
    Output: [batch_size] x ... x [out_size] tensor'''

    def __init__(self, in_size, out_size, nl=nn.ReLU(),
                 drop=0., bias=True, excitability=False, excit_buffer=False, batch_norm=False, gated=False):
        super().__init__()
        if drop>0:
            self.dropout = nn.Dropout(drop)
        self.linear = em.LinearExcitability(in_size, out_size, bias=False if batch_norm else bias,
                                            excitability=excitability, excit_buffer=excit_buffer)
        if batch_norm:
            self.bn = nn.BatchNorm1d(out_size)
        if gated:
            self.gate = nn.Linear(in_size, out_size)
            self.sigmoid = nn.Sigmoid()
        if isinstance(nl, nn.Module):
            self.nl = nl
        elif not nl=="none":
            self.nl = nn.ReLU() if nl == "relu" else (nn.LeakyReLU() if nl == "leakyrelu" else modules.Identity())

    def forward(self, x, return_pa=False, **kwargs):
        input = self.dropout(x) if hasattr(self, 'dropout') else x
        pre_activ = self.bn(self.linear(input)) if hasattr(self, 'bn') else self.linear(input)
        gate = self.sigmoid(self.gate(x)) if hasattr(self, 'gate') else None
        gated_pre_activ = gate * pre_activ if hasattr(self, 'gate') else pre_activ
        output = self.nl(gated_pre_activ) if hasattr(self, 'nl') else gated_pre_activ
        return (output, gated_pre_activ) if return_pa else output

    def list_init_layers(self):
        '''Return list of modules whose parameters could be initialized differently (i.e., conv- or fc-layers).'''
        return [self.linear, self.gate] if hasattr(self, 'gate') else [self.linear]



class fc_layer_split(nn.Module):
    '''Fully connected layer outputting [mean] and [logvar] for each unit.

    Input:  [batch_size] x ... x [in_size] tensor
    Output: tuple with two [batch_size] x ... x [out_size] tensors'''

    def __init__(self, in_size, out_size, nl_mean=nn.Sigmoid(), nl_logvar=nn.Hardtanh(min_val=-4.5, max_val=0.),
                 drop=0., bias=True, excitability=False, excit_buffer=False, batch_norm=False, gated=False):
        super().__init__()

        self.mean = fc_layer(in_size, out_size, drop=drop, bias=bias, excitability=excitability,   # 用ANN来从FC的特征输出，来估计mean 和 var
                             excit_buffer=excit_buffer, batch_norm=batch_norm, gated=gated, nl=nl_mean)
        self.logvar = fc_layer(in_size, out_size, drop=drop, bias=False, excitability=excitability,
                               excit_buffer=excit_buffer, batch_norm=batch_norm, gated=gated, nl=nl_logvar)

    def forward(self, x):
        return (self.mean(x), self.logvar(x))

    def list_init_layers(self):
        '''Return list of modules whose parameters could be initialized differently (i.e., conv- or fc-layers).'''
        list = []
        list += self.mean.list_init_layers()
        list += self.logvar.list_init_layers()
        return list



class fc_layer_fixed_gates(nn.Module):
    '''Fully connected layer, with possibility of returning "pre-activations". Has fixed gates (of specified dimension).

    Input:  [batch_size] x ... x [in_size] tensor         &        [batch_size] x [gate_size]
    Output: [batch_size] x ... x [out_size] tensor'''

    def __init__(self, in_size, out_size, nl=nn.ReLU(),
                 drop=0., bias=True, excitability=False, excit_buffer=False, batch_norm=False,
                 gate_size=0, gating_prop=0.8, device='cuda'):
        super().__init__()
        if drop > 0:
            self.dropout = nn.Dropout(drop)
        self.linear = em.LinearExcitability(in_size, out_size, bias=False if batch_norm else bias,
                                            excitability=excitability, excit_buffer=excit_buffer)
        if batch_norm:
            self.bn = nn.BatchNorm1d(out_size)
        if gate_size>0:
            self.gate_mask = torch.tensor(    # 随机生成的0.0和1.0值，根据给定的概率分布生成， gate-size行，对每个任务代码one-hot来，就通过对one-hot矩阵乘法 取出其中一行。作为gate mask！！
                np.random.choice([0., 1.], size=(gate_size, out_size), p=[gating_prop, 1.-gating_prop]),
                dtype=torch.float, device=device
            )
        if isinstance(nl, nn.Module):
            self.nl = nl
        elif not nl == "none":
            self.nl = nn.ReLU() if nl == "relu" else (nn.LeakyReLU() if nl == "leakyrelu" else modules.Identity())

    def forward(self, x, gate_input=None, return_pa=False):
        input = self.dropout(x) if hasattr(self, 'dropout') else x
        pre_activ = self.bn(self.linear(input)) if hasattr(self, 'bn') else self.linear(input)
        gate = torch.mm(gate_input, self.gate_mask) if hasattr(self, 'gate_mask') else None  # 猜测：gate_input 在train相关代码看到是 1D tensor or 2D tensor，而且要转化为one-HOT， 那么就是一个1*M 的向量。要对应到mask，乘以一个M*out_size的 向量转化成 1*out 就和这一层的FC 结果能对应上了！
        gated_pre_activ = gate * pre_activ if hasattr(self, 'gate_mask') else pre_activ
        output = self.nl(gated_pre_activ) if hasattr(self, 'nl') else gated_pre_activ
        return (output, gated_pre_activ) if return_pa else output

    def list_init_layers(self):
        '''Return list of modules whose parameters could be initialized differently (i.e., conv- or fc-layers).'''
        return [self.linear, self.gate] if hasattr(self, 'gate') else [self.linear]