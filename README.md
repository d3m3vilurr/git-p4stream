## How to use
1. create stream workspace
2. initialize git-p4 repo

    ```bash
    mkdir workdir
    cd workdir
    git init
    git config git-p4.port "p4.repo.addr:1666"
    git config git-p4.user "p4_user_name"
    git config git-p4.client "workspace_name"
    ```

3. sync branch

    ```bash
    git p4 sync --branch=branch_name //stream/branch/subdir/@all
    git config git-p4stream.sync subdir
    git config --add git-p4stream.maps branch_name://stream/branch
    ```

    If you use virtual stream you can set this map information.

    ```bash
    git config --add git-p4stream.maps branch_name://stream/orig://stream/virtual
    ```


4. checkout and work

    ```bash
    git checkout p4/master -b master
    git p4stream switch dev
    git checkout -b develop
    ```
