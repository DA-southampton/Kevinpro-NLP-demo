from torch.utils.data import Dataset
import torch
import torch.nn as nn
from util import *
import os
from model import Transformer
import torch



class DecodeData:
    def __init__(self):
        self.question,self.answer = readFromPair()
        if os.path.exists('dict.txt') == False:
            print("Hit error")
            exit()
        else:
            self.load_dict()

    def tokenizer(self,input):
        ids = []
        for i in input:
            if i in self.word2id:
                ids.append(self.word2id[i])
            else:
                ids.append(self.word2id['[UNK]'])
        return ids

    def padding(self,input):
        while len(input) < 200:
            input.append(self.word2id['[PAD]'])
        input = input[:200]
        return input

    def load_dict(self):
        f = open("dict.txt",'r',encoding = 'utf-8')
        lines = f.readlines()
        self.word2id = {}
        for i in lines:
            data = i.strip().split(' ')
            word = data[0]
            idx = data[1]
            
            self.word2id[word] = int(idx)

        self.id2word = {}
        for i in self.word2id:
            self.id2word[self.word2id[i]] = i
        return 
    
    def encode(self,source_text):
        source_id = self.tokenizer(source_text)
        decode_input = [self.word2id['[BOS]']]
        return source_id,decode_input
    
    def decode(self,result):
        tokens = [ ]
        for i in result:
            if i in self.id2word:
                tokens.append(self.id2word[i])
        return tokens

class CharDataset(Dataset):
    def __init__(self):
        self.question,self.answer = readFromPair()
        if os.path.exists('dict.txt') == False:
            self.build_dict(self.question, self.answer)
        else:
            self.load_dict()

    def load_dict(self):
        f = open("dict.txt",'r',encoding = 'utf-8')
        lines = f.readlines()
        self.word2id = {}
        for i in lines:
            data = i.strip().split(' ')
            word = data[0]
            idx = data[1]
            
            self.word2id[word] = int(idx)

        self.id2word = {}
        for i in self.word2id:
            self.id2word[self.word2id[i]] = i
        return 

    def build_dict(self,source,target):
        self.word2id = {'[PAD]':0,'[BOS]':1,'[EOS]':2,'[UNK]':3}
        id = 4
        for s,t in zip(source,target):
            s = s.replace("\n","")
            for i in s:
                if len(i.strip()) != 0:
                    if i not in self.word2id:
                        self.word2id[i] = id 
                        id += 1
            t = t.replace("\n","")
            for i in t:
                if len(i.strip()) != 0:
                    if i not in self.word2id:
                        self.word2id[i] = id 
                        id += 1
            if id > 30000:
                break
        
        self.id2word = {}
        for i in self.word2id:
            self.id2word[self.word2id[i]] = i
        
        f = open('dict.txt','w',encoding='utf-8')
        for i in self.word2id:
            f.write(i + " " + str(self.word2id[i]) + "\n")
        return

    def tokenizer(self,input):
        ids = []
        for i in input:
            if i in self.word2id:
                ids.append(self.word2id[i])
            else:
                ids.append(self.word2id['[UNK]'])
        return ids

    def padding(self,input):
        while len(input) < 200:
            input.append(self.word2id['[PAD]'])
        input = input[:200]
        return input

    def __len__(self):
        return len(self.question)

    def __getitem__(self, idx):
        source_text = self.question[idx]
        source_id = self.tokenizer(source_text)
        source_id = self.padding(source_id)

        target_text = self.answer[idx]
        target_id = self.tokenizer(target_text)
        target_id = self.padding(target_id)
        decode_input = [self.word2id['[BOS]']] + target_id
        decode_label = target_id + [self.word2id['[EOS]']]
        assert len(decode_input) == len(decode_label)
        assert len(decode_input) == 201
        return torch.tensor(source_id),torch.tensor(decode_input),torch.tensor(decode_label)


import math
import logging

from tqdm import tqdm
import numpy as np

import torch
import torch.optim as optim
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data.dataloader import DataLoader

logger = logging.getLogger(__name__)

class TrainerConfig:
    # optimization parameters
    max_epochs = 10
    batch_size = 64
    learning_rate = 3e-4
    betas = (0.9, 0.95)
    grad_norm_clip = 1.0
    weight_decay = 0.1 # only applied on matmul weights
    # learning rate decay params: linear warmup followed by cosine decay to 10% of original
    lr_decay = False

    ckpt_path = './data/novelModel.pth'
    num_workers = 0 # for DataLoader

    def __init__(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)

@torch.no_grad()
def greedy_decoder(model,input = "医生孩子脑瘫一般有啥表现？,我家宝宝现在是4岁了，我最近感觉他好像是得了脑瘫了，但是我对脑瘫的症状不是很了解，想咨询下医生。小儿脑瘫有哪些表现"):
    model.eval()
    model.cuda()
    decode_steps = 200
    decode_dataset = DecodeData()
    enc_input,dec_input = decode_dataset.encode(input)
    enc_input = torch.tensor(enc_input).unsqueeze(0).cuda()
    dec_input = torch.tensor(dec_input).unsqueeze(0).cuda()
    for k in range(decode_steps):
        dec_logits, enc_self_attns, dec_self_attns, dec_enc_attns = model(enc_input,dec_input)
        _, ix = torch.topk(dec_logits, k=1, dim=-1)
        ix = ix[:,-1]
        ix = ix.reshape(1,-1)
        dec_input = torch.cat((dec_input, ix), dim=1)


    result = dec_input.cpu().numpy().tolist()[0]
    tokens = decode_dataset.decode(result)
    output_string = "".join(tokens)
    output_string = output_string.replace("[PAD]","")
    output_string = output_string.replace("[BOS]","")
    #output_string = output_string.replace("[EOS]","")
    print("Kevin's Transformer Doctor:",output_string)

class TransformerTrainer:
    def __init__(self, model, train_dataset, test_dataset, config):
        self.model = model
        self.train_dataset = train_dataset
        self.test_dataset = test_dataset
        self.config = config

        # take over whatever gpus are on the system
        self.device = 'cpu'
        if torch.cuda.is_available():
            self.device = torch.cuda.current_device()
            self.model.to(self.device)
            #self.model = torch.nn.DataParallel(self.model).to(self.device)

    def save_checkpoint(self):
        # DataParallel wrappers keep raw model object in .module attribute
        raw_model = self.model.module if hasattr(self.model, "module") else self.model
        logger.info("saving %s", self.config.ckpt_path)
        torch.save(raw_model.state_dict(), self.config.ckpt_path)

    def train(self):
        model, config = self.model, self.config
        raw_model = model.module if hasattr(self.model, "module") else model
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=config.learning_rate, betas=config.betas)
        crossentropyloss = nn.CrossEntropyLoss()
        def run_epoch(split):
            is_train = split == 'train'
            model.train(is_train)
            data = self.train_dataset if is_train else self.test_dataset
            loader = DataLoader(data, shuffle=True, pin_memory=True,
                                batch_size=config.batch_size,
                                num_workers=config.num_workers)

            losses = []
            pbar = tqdm(enumerate(loader), total=len(loader)) if is_train else enumerate(loader)
            for it, (source,decode_input,decode_label) in pbar:

                # place data on the correct device
                source = source.to(self.device)
                decode_input = decode_input.to(self.device)
                decode_label = decode_label.to(self.device)
                # forward the model
                with torch.set_grad_enabled(is_train):
                    dec_logits, enc_self_attns, dec_self_attns, dec_enc_attns = model(source, decode_input)
                    dec_logits = dec_logits.view(-1, dec_logits.size(-1))
                    loss = crossentropyloss(dec_logits,decode_label.reshape(-1))
                    loss = loss.mean() # collapse all losses if they are scattered on multiple gpus
                    losses.append(loss.item())

                if is_train:

                    # backprop and update the parameters
                    model.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), config.grad_norm_clip)
                    optimizer.step()


                    lr = config.learning_rate

                    # report progress
                    pbar.set_description(f"epoch {epoch+1} iter {it}: train loss {loss.item():.5f}. lr {lr:e}")

            if not is_train:
                test_loss = float(np.mean(losses))
                logger.info("test loss: %f", test_loss)
                return test_loss

        best_loss = float('inf')
        self.tokens = 0 # counter used for learning rate decay
        for epoch in range(config.max_epochs):
            self.save_checkpoint()
            run_epoch('train')
            if self.test_dataset is not None:
                test_loss = run_epoch('test')

            # supports early stopping based on the test loss, or just save always if no test set is provided
            good_model = self.test_dataset is None or test_loss < best_loss
            greedy_decoder(model)
            self.save_checkpoint()
            # if self.config.ckpt_path is not None and good_model:
            #     best_loss = test_loss
            #     self.save_checkpoint()

