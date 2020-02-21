from trainer.glove_utils import build_glove_model, get_glove_dataset, init_params, parse_args
from trainer.utils import file_lines, get_keras_callbacks, get_loss_fn, get_optimizer


def main():
    args = parse_args()
    params = init_params(args.__dict__)

    # set up model and compile
    model = build_glove_model(file_lines(params["vocab_txt"]), params["embedding_size"], params["l2_reg"])
    model.compile(optimizer=get_optimizer(params["optimizer"], learning_rate=params["learning_rate"]),
                  loss=get_loss_fn("MeanSquaredError"))

    # set up train, validation dataset
    dataset_args = {
        "file_pattern": params["train_csv"],
        "vocab_txt": params["vocab_txt"],
        "batch_size": params["batch_size"],
    }
    train_dataset = get_glove_dataset(**dataset_args, num_epochs=None)
    validation_dataset = get_glove_dataset(**dataset_args)

    # train and evaluate
    history = model.fit(
        train_dataset,
        epochs=params["train_steps"] // params["steps_per_epoch"],
        callbacks=get_keras_callbacks(params["job_dir"]),
        validation_data=validation_dataset,
        steps_per_epoch=params["steps_per_epoch"],
    )

    # # estimator
    # estimator = get_keras_estimator(model, params["job_dir"])
    #
    # # input functions
    # dataset_args = {"dataset_fn": get_glove_dataset, **dataset_args}
    # train_input_fn = get_keras_estimator_input_fn(**dataset_args, num_epochs=None)
    # eval_input_fn = get_keras_estimator_input_fn(**dataset_args)
    #
    # # train, eval spec
    # train_spec = get_train_spec(train_input_fn, params["train_steps"])
    # exporter = get_exporter(get_serving_input_fn(**CONFIG["serving_input_fn_args"]))
    # eval_spec = get_eval_spec(eval_input_fn, exporter)
    #
    # # train and evaluate
    # tf.estimator.train_and_evaluate(estimator, train_spec, eval_spec)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
