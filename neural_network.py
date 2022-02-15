import math
import torch
import torch.nn as nn
import random
import numpy as np
import torch.nn.functional as F
import argparse
import os
import shutil
import time
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim
import torch.utils.data
import torchvision.transforms as transforms
import torchvision.datasets as datasets
from torch.autograd import Variable
from torch.utils.data import Dataset
from torch.utils.data.dataset import random_split
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt


class BasicBlock(nn.Module):
    def __init__(self, in_planes, out_planes, stride, dropRate=0.0):
        super(BasicBlock, self).__init__()
        self.bn1 = nn.BatchNorm2d(in_planes)
        self.relu1 = nn.ReLU(inplace=True)
        self.conv1 = nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                               padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_planes)
        self.relu2 = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(out_planes, out_planes, kernel_size=3, stride=1,
                               padding=1, bias=False)
        self.droprate = dropRate
        self.equalInOut = (in_planes == out_planes)
        self.convShortcut = (not self.equalInOut) and nn.Conv2d(in_planes, out_planes, kernel_size=1, stride=stride,
                                                                padding=0, bias=False) or None
    def forward(self, x):
        if not self.equalInOut:
            x = self.relu1(self.bn1(x))
        else:
            out = self.relu1(self.bn1(x))
        out = self.relu2(self.bn2(self.conv1(out if self.equalInOut else x)))
        if self.droprate > 0:
            out = F.dropout(out, p=self.droprate, training=self.training)
        out = self.conv2(out)
        return torch.add(x if self.equalInOut else self.convShortcut(x), out)


class NetworkBlock(nn.Module):
    def __init__(self, nb_layers, in_planes, out_planes, block, stride, dropRate=0.0):
        super(NetworkBlock, self).__init__()
        self.layer = self._make_layer(block, in_planes, out_planes, nb_layers, stride, dropRate)
    def _make_layer(self, block, in_planes, out_planes, nb_layers, stride, dropRate):
        layers = []
        for i in range(int(nb_layers)):
            layers.append(block(i == 0 and in_planes or out_planes, out_planes, i == 0 and stride or 1, dropRate))
        return nn.Sequential(*layers)
    def forward(self, x):
        return self.layer(x)


class WideResNet(nn.Module):
    def __init__(self, depth, num_classes, widen_factor=1, dropRate=0.0):
        super(WideResNet, self).__init__()
        nChannels = [16, 16 * widen_factor, 32 * widen_factor, 64 * widen_factor]
        assert ((depth - 4) % 6 == 0)
        n = (depth - 4) / 6
        block = BasicBlock
        # 1st conv before any network block
        self.conv1 = nn.Conv2d(3, nChannels[0], kernel_size=3, stride=1,
                               padding=1, bias=False)
        # 1st block
        self.block1 = NetworkBlock(n, nChannels[0], nChannels[1], block, 1, dropRate)
        # 2nd block
        self.block2 = NetworkBlock(n, nChannels[1], nChannels[2], block, 2, dropRate)
        # 3rd block
        self.block3 = NetworkBlock(n, nChannels[2], nChannels[3], block, 2, dropRate)
        # global average pooling and classifier
        self.bn1 = nn.BatchNorm2d(nChannels[3])
        self.relu = nn.ReLU(inplace=True)
        self.fc = nn.Linear(nChannels[3], num_classes)
        self.nChannels = nChannels[3]
        self.softmax = nn.Softmax()
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                m.bias.data.zero_()
    def forward(self, x):
        out = self.conv1(x)
        out = self.block1(out)
        out = self.block2(out)
        out = self.block3(out)
        out = self.relu(self.bn1(out))
        out = F.avg_pool2d(out, 8)
        out = out.view(-1, self.nChannels)
        out = self.fc(out)
        out = self.softmax(out)
        return out

    
# simple conv network
# (argument 2 of the first nn.Conv2d, and argument 1 of the second nn.Conv2d – they need to be the same number)
class NetSimple(nn.Module):
    def __init__(self, num_classes, width1 = 6, width2 = 16,ff_units1 = 120, ff_units2 = 84):
        super().__init__()
        self.conv1 = nn.Conv2d(3, width1, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(width1, width2, 5)
        self.fc1 = nn.Linear(width2 * 5 * 5, ff_units1)
        self.fc2 = nn.Linear(ff_units1, ff_units2)
        self.fc3 = nn.Linear(ff_units2, num_classes)
        self.softmax = nn.Softmax()

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1) # flatten all dimensions except batch
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        x = self.softmax(x)
        return x
    
class NetSimpleRaw(nn.Module):
    def __init__(self, num_classes, width1 = 6, width2 = 16,ff_units1 = 120, ff_units2 = 84):
        super().__init__()
        self.conv1 = nn.Conv2d(3, width1, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(width1, width2, 5)
        self.fc1 = nn.Linear(width2 * 5 * 5, ff_units1)
        self.fc2 = nn.Linear(ff_units1, ff_units2)
        self.fc3 = nn.Linear(ff_units2, num_classes)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1) # flatten all dimensions except batch
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x

    
class NetSimpleRejector(nn.Module):
    def __init__(self, params_h, params_r):
        super().__init__()
        self.net_h = NetSimpleRaw(*params_h)
        self.net_r = NetSimpleRaw(*params_r)
        self.softmax = nn.Softmax()

    def forward(self, x):
        x_h = self.net_h(x)
        x_r = self.net_r(x)
        x = torch.cat((x_h, x_r), 1)
        x = self.softmax(x)
        return x

    
class NetComplex(nn.Module):
    def __init__(self, num_classes, width1 = 6, width2 = 16,ff_units1 = 120, ff_units2 = 84):
        super().__init__()
        self.conv1 = nn.Conv2d(3, width1, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(width1, width2, 5)
        self.conv3 = nn.Conv2d(width2, width2, 5)
        self.fc1 = nn.Linear(width2 * 3 * 3, ff_units1)
        self.fc2 = nn.Linear(ff_units1, ff_units2)
        self.fc3 = nn.Linear(ff_units2, num_classes)
        self.softmax = nn.Softmax()

    def forward(self, x):
        to_print_size = False
        x = self.pool(F.relu(self.conv1(x)))
        if to_print_size:
            print(x.size())
        x = F.relu(self.conv2(x))
        if to_print_size:
            print(x.size())
        x = self.pool(F.relu(self.conv3(x)))
        if to_print_size:
            print(x.size())
        x = torch.flatten(x, 1) # flatten all dimensions except batch
        if to_print_size:
            print(x.size())
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        x = self.softmax(x)
        return x

