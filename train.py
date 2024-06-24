import json, os
os.environ["CUDA_VISIBLE_DEVICES"] = "1"

import argparse
import torch
from transformers import LlamaForCausalLM, LlamaTokenizer
from transformers import GenerationConfig
from transformers import TrainingArguments, DataCollatorForLanguageModeling
from trl import SFTTrainer
from datasets import load_dataset
from peft import get_peft_model, LoraConfig
from safetensors.torch import load_file

generation_config = GenerationConfig(
    temperature=0.2,
    top_k=40,
    top_p=0.9,
    do_sample=True,
    num_beams=1,
    repetition_penalty=1.2,
    max_new_tokens=400
)

training_args = TrainingArguments(
    output_dir="./output",
    auto_find_batch_size=True,
    per_device_train_batch_size=36,
    per_device_eval_batch_size=36,
    warmup_ratio=0.03,
    learning_rate=1e-5,
    lr_scheduler_type="cosine",
    weight_decay=0.01,
    num_train_epochs=2,
    bf16=True,
    gradient_accumulation_steps=4,
    log_level="info",
    logging_steps=0.1,
    eval_strategy="epoch",
    save_strategy="epoch",
    eval_accumulation_steps=4,
    save_steps=0.1,
    save_total_limit=3,
    save_safetensors=True,
    max_grad_norm=0.3,
    seed=42
)

parser = argparse.ArgumentParser()
parser.add_argument('--model', default="NanoAbLLaMAmodel", type=str, help="The local path of the model.")
parser.add_argument('--input_file', default=None, help="Training dataset, Using a .csv file with only one column of data named 'text'")
parser.add_argument('--output_file', default=None, help="model will be saved in this file.")
args = parser.parse_args()

load_type = torch.bfloat16
model = LlamaForCausalLM.from_pretrained(
        args.model,
        torch_dtype=load_type,
        low_cpu_mem_usage=True,
        quantization_config=None,
        device_map="auto"
    )

tokenizer = LlamaTokenizer.from_pretrained(args.model)
tokenizer.padding_side = 'right'
tokenizer.pad_token_id = 0
data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

llama_peft_config = LoraConfig(
    task_type="CAUSAL_LM",
    r=64,
    lora_alpha=128,
    lora_dropout=0.05,
    bias="none",
    modules_to_save=[
        "embed_tokens",
        "lm_head"
    ],
    target_modules=[
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj"
    ]
)

def process_function(datasets):
    tokenizer_data = tokenizer(datasets['data'], padding=True)
    return tokenizer_data

def preprocess_data(path):
    # 将数据处理成Dataset
    dataset = load_dataset("csv", data_files=path, split="train")
    datasets = dataset.train_test_split(test_size=0.2)
    return datasets

def train(device):
    #使用peft进行处理
    peft_model = get_peft_model(model, llama_peft_config)
    peft_model.print_trainable_parameters()

    # 数据处理部分
    datasets = preprocess_data(args.input_file)

    # trainer
    trainer = SFTTrainer(
        model = peft_model,
        args = training_args,
        train_dataset = datasets['train'],
        eval_dataset = datasets['test'],
        peft_config=llama_peft_config,
        dataset_text_field="text",
        tokenizer=tokenizer,
        data_collator=data_collator,
        max_seq_length=256
    )

    #模型训练
    trainer.train()

    #保存模型
    trainer.model.save_pretrained(args.output_file)

if __name__ == '__main__':
    if args.input_file is None:
        raise ValueError("input_file is None.")
    if args.onput_file is None:
        raise ValueError("onput_file is None.")
    if torch.cuda.is_available():
        device = torch.device(0)
    else:
        raise ValueError("No GPU available.")

    #调用训练函数
    train(device)