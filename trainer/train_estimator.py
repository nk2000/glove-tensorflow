import tensorflow as tf

from trainer.config import CONFIG, EMBEDDING_SIZE, L2_REG, LEARNING_RATE, OPTIMIZER, TARGET, VOCAB_TXT
from trainer.glove_utils import build_glove_model, get_string_id_table, init_params, parse_args
from trainer.utils import (
    get_eval_spec, get_exporter, get_keras_dataset_input_fn, get_loss_fn, get_minimise_op, get_optimizer,
    get_run_config, get_serving_input_fn, get_train_spec,
)


def model_fn(features, labels, mode, params):
    vocab_txt = params.get("vocab_txt", VOCAB_TXT)
    embedding_size = params.get("embedding_size", EMBEDDING_SIZE)
    l2_reg = params.get("l2_reg", L2_REG)
    optimizer_name = params.get("optimizer", OPTIMIZER)
    learning_rate = params.get("learning_rate", LEARNING_RATE)

    if set(features.keys()) == {"features", "sample_weights"}:
        sample_weights = features["sample_weights"]
        features = features["features"]
    else:
        sample_weights = {TARGET: None}

    with tf.name_scope("features"):
        string_id_table = get_string_id_table(vocab_txt)
        inputs = {key: string_id_table.lookup(values) for key, values in features.items()}

    model = build_glove_model(vocab_txt, embedding_size, l2_reg)
    training = (mode == tf.estimator.ModeKeys.TRAIN)
    predict_value = model(inputs, training=training)

    # prediction
    predictions = {"predict_value": predict_value}
    if mode == tf.estimator.ModeKeys.PREDICT:
        return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

    # evaluation
    with tf.name_scope("losses"):
        mse_loss = get_loss_fn("MeanSquaredError")(
            labels[TARGET], tf.expand_dims(predict_value, -1), sample_weights[TARGET],
        )
        # []
        reg_losses = model.get_losses_for(None) + model.get_losses_for(features)
        loss = tf.math.add_n([mse_loss] + reg_losses)
        # []
    if mode == tf.estimator.ModeKeys.EVAL:
        return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions, loss=loss)

    # training
    optimizer = get_optimizer(optimizer_name, learning_rate=learning_rate)
    minimise_op = get_minimise_op(loss, optimizer, model.trainable_variables)
    update_ops = model.get_updates_for(None) + model.get_updates_for(features)
    train_op = tf.group(*minimise_op, *update_ops, name="train_op")
    if mode == tf.estimator.ModeKeys.TRAIN:
        return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions, loss=loss, train_op=train_op)


def get_estimator(job_dir, params):
    estimator = tf.estimator.Estimator(
        model_fn=model_fn,
        model_dir=job_dir,
        config=get_run_config(),
        params=params
    )
    return estimator


def main():
    args = parse_args()
    params = init_params(args.__dict__)

    # estimator
    estimator = get_estimator(params["job_dir"], params)

    # input functions
    dataset_args = {
        "file_pattern": params["train_csv"],
        "batch_size": params["batch_size"],
        **CONFIG["dataset_args"],
    }
    train_input_fn = get_keras_dataset_input_fn(**dataset_args, num_epochs=None)
    eval_input_fn = get_keras_dataset_input_fn(**dataset_args)

    # train, eval spec
    train_spec = get_train_spec(train_input_fn, params["train_steps"])
    exporter = get_exporter(get_serving_input_fn(**CONFIG["serving_input_fn_args"]))
    eval_spec = get_eval_spec(eval_input_fn, exporter)

    # train and evaluate
    tf.estimator.train_and_evaluate(estimator, train_spec, eval_spec)


if __name__ == '__main__':
    main()
