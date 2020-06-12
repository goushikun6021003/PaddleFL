#   Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""

This module provides an example of DLG attack on MNIST. Please refer to
README for more details.

"""

from __future__ import print_function

import argparse
import numpy

import paddle
import paddle.fluid as fluid
from PIL import Image
from paddle.fluid.param_attr import ParamAttr

from dlg import dlg


def parse_args():
    """
    Parse command line arguments.
    :return:
    """
    parser = argparse.ArgumentParser("DLG")
    parser.add_argument("--use_gpu",
                        type=bool, default=False,
                        help="Whether to use GPU or not.")
    parser.add_argument("--batch_size",
                        type=int, default=2,
                        help="The batch size of normal training.")
    parser.add_argument("--iterations",
                        type=int, default=3000,
                        help="The iterations of attacking training.")
    parser.add_argument("--learning_rate",
                        type=float, default=-8.5,
                        help="The learning rate of attacking training.")
    parser.add_argument("--result_dir",
                        type=str, default="./att_results",
                        help="the directory for saving attack result.")
    args = parser.parse_args()
    return args


def network(img, label):
    """
    The network of model.
    :param img: the feature of training data
    :param label: the label of training data
    :return: the prediction and average loos
    """
    # ensure that dummy data use the same initialized
    # model params with real data
    param_attr = ParamAttr(name="fc.w_0")
    bias_attr = ParamAttr(name="fc.b_0")
    prediction = fluid.layers.fc(input=img,
                                 size=10,
                                 act="softmax",
                                 param_attr=param_attr,
                                 bias_attr=bias_attr)
    loss = fluid.layers.cross_entropy(input=prediction, label=label)
    avg_loss = fluid.layers.mean(loss)
    return prediction, avg_loss


def train_and_attack(args):
    """
    The training procedure that starts from several normal training steps as usual,
    but entrance the dlg method as soon as the gradients of target data are obtained.
    :param args: the execution parameters.
    :return:
    """
    if args.use_gpu and not fluid.core.is_compiled_with_cuda():
        return

    startup_program = fluid.default_startup_program()
    main_program = fluid.default_main_program()

    train_reader = paddle.batch(
        paddle.reader.shuffle(paddle.dataset.mnist.train(), buf_size=500),
        batch_size=args.batch_size)

    img = fluid.data(name="img", shape=[None, 28, 28], dtype="float32")
    label = fluid.data(name="label", shape=[None, 1], dtype="int64")

    prediction, avg_loss = network(img, label)

    optimizer = fluid.optimizer.Adam(learning_rate=0.001)

    # ensure that the model parameters are not be updated before attack finished.
    _ = optimizer.backward(avg_loss)

    place = fluid.CUDAPlace(0) if args.use_gpu else fluid.CPUPlace()
    exe = fluid.Executor(place)

    exe.run(startup_program)

    for step_id, data in enumerate(train_reader()):
        params = main_program.global_block().all_parameters()
        grad_param = [param.name + "@GRAD" for param in params if param.trainable]

        # save the target data for checking out the effectiveness of attack
        image = Image.fromarray((data[0][0] * 255).reshape(28, 28).astype(numpy.uint8))
        image.save("./target.png")

        target_x = numpy.array(data[0][0]).reshape((1, 28, 28))
        target_y = numpy.array(data[0][1]).reshape(1, 1)

        metrics = exe.run(
            main_program,
            feed={"img": target_x, "label": target_y},
            fetch_list=[avg_loss] + grad_param)

        # entrance DLG attack procedure at the first step
        if step_id == 0:
            # the gradients of model parameters generated by target data
            origin_grad = metrics[1:]
            dlg.dlg_attack(args, img, label, network, exe, origin_grad)


if __name__ == "__main__":
    arguments = parse_args()
    train_and_attack(arguments)
