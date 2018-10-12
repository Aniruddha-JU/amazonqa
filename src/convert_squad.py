import os
import torch
import string
import pandas as pd
import numpy as np
from tqdm import tqdm
import nltk
from nltk.corpus import stopwords

import config
import constants as C
from data.vocabulary import Vocabulary
from data import review_utils
import string
from evaluator.evaluator import COCOEvalCap
from operator import itemgetter, attrgetter
import json

DEBUG = False

class AmazonDataset(object):
    def __init__(self, params):
        self.review_select_num = params[C.REVIEW_SELECT_NUM]
        self.review_select_mode = params[C.REVIEW_SELECT_MODE]

        category = params[C.CATEGORY]
        self.train_path = '%s/train-%s.pickle' % (C.INPUT_DATA_PATH, category)
        self.val_path = '%s/val-%s.pickle' % (C.INPUT_DATA_PATH, category)
        self.test_path = '%s/test-%s.pickle' % (C.INPUT_DATA_PATH, category)

    @staticmethod
    def tokenize(text):
        punctuations = string.punctuation.replace("\'", '')

        for ch in punctuations:
            text = text.replace(ch, " " + ch + " ")

        tokens = text.split()
        for i, token in enumerate(tokens):
            if not token.isupper():
                tokens[i] = token.lower()
        return tokens

    def find_answer_spans(self, max_num_spans, answer_span_lens, answers, context):
        context = context.split(' ')
        gold_answers_dict = {}
        gold_answers_dict[0] = [answer[C.TEXT] for answer in answers]
        answers = []
        for answer_span_len in answer_span_lens:
            for index in range(len(context)-answer_span_len):
                span = context[index: index+answer_span_len]
                generated_answer_dict = {}
                generated_answer_dict[0] = [span]
                
                score = COCOEvalCap.compute_scores(gold_answers_dict, generated_answer_dict)['Bleu_2']
                answers.append((score, {
                    'answer_start': index,
                    'text': span    
                }))

        return [i[1] for i in sorted(answers, reverse=True, key=itemgetter(0))[:max_num_spans]]

    def save_data(self, path, max_review_len, answer_span_lens, max_num_spans, filename='temp.csv'):
        print("Creating Dataset from " + path)
        assert os.path.exists(path)

        with open(path, 'rb') as f:
            dataFrame = pd.read_pickle(f)
            if DEBUG:
                dataFrame = dataFrame.iloc[:5]

        print('Number of products: %d' % len(dataFrame))
        stop_words = set(stopwords.words('english'))

        paragraphs = []
        count = 0
        for (_, row) in dataFrame.iterrows():
            print(count)
            count += 1
            if count % 10 != 0:
              continue
            # combine all or get only the reviews
            reviews = row[C.REVIEWS_LIST]
            review_tokens = []
            review_texts = []
            for review in reviews:
                sentences = nltk.sent_tokenize(review[C.TEXT])
                bufr = []
                buffer_len = 0
                for sentence in sentences:
                    buffer_len += len(self.tokenize(sentence))
                    if buffer_len > max_review_len:
                        review_texts.append(' '.join(bufr))
                        bufr = []
                        buffer_len = 0
                    else:
                        bufr.append(sentence)

            review_tokens = [self.tokenize(r) for r in review_texts]
            review_tokens = [[token for token in r if token not in stop_words and token not in string.punctuation] for r in review_tokens]
            inverted_index = _create_inverted_index(review_tokens)
            review_tokens = list(map(set, review_tokens))

            qas = []
            for qid, question in enumerate(row[C.QUESTIONS_LIST]):
                question_text = question[C.TEXT]
                question_tokens = self.tokenize(question_text)

                # Get Context
                scores_q, top_reviews_q = review_utils.top_reviews_and_scores(
                    set(question_tokens),
                    review_tokens,
                    inverted_index,
                    None,
                    review_texts,
                    self.review_select_mode,
                    self.review_select_num
                )
                context = ' '.join(top_reviews_q)

                answers = question[C.ANSWERS]
                new_answers = self.find_answer_spans(max_num_spans, answer_span_lens, answers, context)
                # max_num_spans, answer_span_lens, answers, context

                # is_answerable = find_answerable(question_text, context)
                is_answerable = False

                # New Question
                qas.append({
                    'id': qid,
                    'is_impossible': is_answerable,
                    'question': question_text,
                    'answers': new_answers,
                })
            
            paragraphs.append({
                'context': context,
                'qas': qas,
            })
        
        data = {
            'title': 'AmazonDataset',
            'paragraphs': paragraphs,
        }
        
        with open(filename, 'w') as outfile:
          json.dump(data, outfile)

def _reviews_and_answer(top_reviews_a, answer_texts, i):
    if len(top_reviews_a) <= i:
        return ''    
    return 'Answer:\n%s\n\nReviews:\n%s' % (answer_texts[i], _enumerated_list_as_string(top_reviews_a[i]))

def _create_inverted_index(review_tokens):
    term_dict = {}
    # TODO: Use actual review IDs
    for doc_id, tokens in enumerate(review_tokens):
        for token in tokens:
            if token in term_dict:
                if doc_id in term_dict[token]:
                    term_dict[token][doc_id] += 1
                else:
                    term_dict[token][doc_id] = 1
            else:
                term_dict[token] = {doc_id: 1}
    return term_dict

def _enumerated_list_as_string(l):
    return '\n'.join(_enumerate_list(l))

def _enumerate_list(l):
    return ['%d) %s' % (rid + 1, r) for rid, r in enumerate(l) if r != '']

def main():
    seed = 1
    max_review_len = 50
    answer_span_lens = range(1, 10)
    max_num_spans = 5
    np.random.seed(seed)
    model_name = C.LM_QUESTION_ANSWERS_REVIEWS
    params = config.get_model_params(model_name)
    params[C.MODEL_NAME] = model_name

    params[C.REVIEW_SELECT_MODE] = C.BM25
    dataset = AmazonDataset(params)
    path = dataset.test_path
    dataset.save_data(
        path,
        max_review_len,
        answer_span_lens,
        max_num_spans,
        filename='squad_%s_%d_%d.csv' % (params[C.CATEGORY], max_review_len, seed)
    )

if __name__ == '__main__':
    main()