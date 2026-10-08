/*
 * Shared confirmation dialog (#confirmModal in base.html).
 *
 * ChaosModal.confirm({ title, subtitle, body, confirmText })
 * resolves to true when confirmed, false otherwise.
 * `body` is an optional DOM node shown inside the dialog.
 *
 * ChaosModal.notice({ title, subtitle }) only informs: one OK button.
 */

window.ChaosModal = {

    confirm({ title, subtitle, body, confirmText }) {

        return new Promise(resolve => {

            modalTitle.textContent = title;
            modalSubtitle.textContent = subtitle;

            modalBody.innerHTML = "";

            if (body) modalBody.appendChild(body);

            modalConfirm.textContent = confirmText;
            modalConfirm.disabled = false;

            modalCancel.classList.remove("hidden");

            const finish = result => {
                confirmModal.classList.add("hidden");
                resolve(result);
            };

            modalConfirm.onclick = e => { e.preventDefault(); finish(true); };
            modalCancel.onclick = e => { e.preventDefault(); finish(false); };
            modalClose.onclick = e => { e.preventDefault(); finish(false); };
            confirmModal.onclick = e => {
                if (e.target === confirmModal) finish(false);
            };

            confirmModal.classList.remove("hidden");

        });

    },


    async notice({ title, subtitle }) {

        const done = this.confirm({ title, subtitle, confirmText: "OK" });

        modalCancel.classList.add("hidden");

        await done;

        modalCancel.classList.remove("hidden");

    },


    close() {

        confirmModal.classList.add("hidden");

    }

};
