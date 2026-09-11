document.addEventListener('DOMContentLoaded', () => {
    // Override default alert with custom modal
    window.alert = function(message) {
        const modal = document.getElementById('custom-alert-modal');
        const msgEl = document.getElementById('custom-alert-message');
        if (modal && msgEl) {
            msgEl.innerText = message;
            modal.style.display = 'flex';
            if (typeof setSystemState === 'function') setSystemState(true);
        }
    };
    
    const closeAlertBtn = document.getElementById('close-alert-btn');
    if (closeAlertBtn) {
        closeAlertBtn.onclick = () => {
            document.getElementById('custom-alert-modal').style.display = 'none';
            if (typeof setSystemState === 'function') setSystemState(false);
        };
    }

    // Custom Confirm Modal
    window.customConfirm = function(message, onConfirm) {
        const modal = document.getElementById('custom-confirm-modal');
        const msgEl = document.getElementById('custom-confirm-message');
        const yesBtn = document.getElementById('confirm-yes-btn');
        const noBtn = document.getElementById('confirm-no-btn');
        
        if (modal && msgEl && yesBtn && noBtn) {
            msgEl.innerText = message;
            modal.style.display = 'flex';
            
            yesBtn.onclick = () => {
                modal.style.display = 'none';
                onConfirm();
            };
            noBtn.onclick = () => {
                modal.style.display = 'none';
            };
        }
    };

    // --- System State Management ---
    let currentCameraActive = false;

    function updateCameraButtonUI(active) {
        currentCameraActive = active;
        const btn = document.getElementById('toggle-camera-btn');
        if (btn) {
            if (active) {
                btn.innerText = "⏸ Pause Camera";
                btn.style.background = "#ef4444";
            } else {
                btn.innerText = "▶ Start Camera";
                btn.style.background = "linear-gradient(135deg, #10b981, #059669)";
            }
        }
    }

    // Auto-enable camera on page load
    fetch('/api/system/state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_enabled: true, system_paused: false })
    })
    .then(res => res.json())
    .then(() => {
        updateCameraButtonUI(true);
        const mainFeed = document.getElementById('camera-feed');
        if (mainFeed) mainFeed.src = "/video_feed?" + new Date().getTime();
    })
    .catch(err => console.error("Failed to sync system state:", err));

    window.toggleMainCamera = function() {
        const nextState = !currentCameraActive;
        fetch('/api/system/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ camera_enabled: nextState, system_paused: !nextState })
        }).then(() => {
            updateCameraButtonUI(nextState);
            const mainFeed = document.getElementById('camera-feed');
            if (mainFeed) mainFeed.src = "/video_feed?" + new Date().getTime();
        });
    };

    window.setSystemState = function(paused) {
        fetch('/api/system/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ system_paused: paused, camera_enabled: !paused })
        });
    };

    window.switchCamera = function() {
        const mainFeed = document.getElementById('camera-feed');
        if (mainFeed) mainFeed.style.opacity = '0.5';
        
        fetch('/api/system/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ switch_camera: true })
        }).then(() => {
            console.log("Requested camera switch");
            setTimeout(() => { if (mainFeed) mainFeed.style.opacity = '1'; }, 1500);
        });
    };

    // Elements
    const authModal = document.getElementById('admin-auth-modal');
    const dashboardModal = document.getElementById('admin-dashboard-modal');
    
    const openAdminBtn = document.getElementById('open-admin-btn');
    const closeDashBtn = document.getElementById('close-dashboard-btn');
    const closeAuthBtn = document.getElementById('close-auth-btn');
    
    const submitAuthBtn = document.getElementById('submit-auth-btn');
    const passwordInput = document.getElementById('admin-password');
    const authError = document.getElementById('auth-error');

    // Status Polling & Live Side-Panel HUD Updates
    let lastSpokenStatus = "";
    async function pollStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            // Side Panel Elements
            const badge = document.getElementById('side-status-badge');
            const progressBar = document.getElementById('side-progress-bar');
            const progressText = document.getElementById('side-progress-text');
            const alertBox = document.getElementById('side-alert-box');

            const dur = data.gaze_duration || 0.0;
            const reqDur = data.required_duration || 0.5;
            const pct = Math.min(100, Math.max(0, (dur / reqDur) * 100));

            if (progressBar) progressBar.style.width = pct + '%';
            if (progressText) progressText.innerText = `${dur.toFixed(1)}s / ${reqDur.toFixed(1)}s`;

            if (badge) {
                const msg = data.gaze_status || "POSITION FACE IN TARGET ZONE";
                badge.innerText = msg;

                if (msg.includes("PERFECT") || pct >= 100) {
                    badge.style.background = "rgba(16, 185, 129, 0.2)";
                    badge.style.borderColor = "rgba(16, 185, 129, 0.5)";
                    badge.style.color = "#10b981";
                } else if (msg.includes("MOVE") || msg.includes("TURNED")) {
                    badge.style.background = "rgba(245, 158, 11, 0.2)";
                    badge.style.borderColor = "rgba(245, 158, 11, 0.5)";
                    badge.style.color = "#f59e0b";
                } else {
                    badge.style.background = "rgba(59, 130, 246, 0.15)";
                    badge.style.borderColor = "rgba(59, 130, 246, 0.3)";
                    badge.style.color = "#3b82f6";
                }
            }

            const toast = document.getElementById('camera-popup-toast');
            const toastIcon = document.getElementById('toast-icon');
            const toastTitle = document.getElementById('toast-title');
            const toastDesc = document.getElementById('toast-desc');

            if (data.status_text && data.status_text.startsWith("SUCCESS|")) {
                let parts = data.status_text.split("|");
                let userName = parts[1];
                let msgDetail = parts[2] || "Logged in successfully";

                if (toast && toastTitle && toastDesc) {
                    toast.style.display = 'block';
                    toast.style.borderColor = '#10b981';
                    toast.style.boxShadow = '0 12px 35px rgba(0, 0, 0, 0.7), 0 0 25px rgba(16, 185, 129, 0.4)';
                    if (toastIcon) toastIcon.innerText = '✅';
                    toastTitle.innerText = `Clock In Successful!`;
                    toastTitle.style.color = '#10b981';
                    toastDesc.innerHTML = `Welcome <strong>${userName}</strong><br><span style="font-size:0.85rem; color:#94a3b8;">${msgDetail}</span>`;
                }

                if (alertBox) {
                    alertBox.style.display = 'block';
                    alertBox.style.background = "rgba(16, 185, 129, 0.25)";
                    alertBox.style.border = "1px solid rgba(16, 185, 129, 0.5)";
                    alertBox.style.color = "#10b981";
                    alertBox.innerText = `✅ ${userName}: ${msgDetail}`;
                }

                if (lastSpokenStatus !== data.status_text) {
                    lastSpokenStatus = data.status_text;
                    speakText(`Welcome ${userName}. Logged in successfully.`);
                }
            } else if (data.status_text && data.status_text.startsWith("PENDING|")) {
                let parts = data.status_text.split("|");
                let userName = parts[1];
                let msgDetail = parts[2] || "Late Arrival Pending Admin Approval";

                if (toast && toastTitle && toastDesc) {
                    toast.style.display = 'block';
                    toast.style.borderColor = '#f59e0b';
                    toast.style.boxShadow = '0 12px 35px rgba(0, 0, 0, 0.7), 0 0 25px rgba(245, 158, 11, 0.4)';
                    if (toastIcon) toastIcon.innerText = '⏳';
                    toastTitle.innerText = `Pending Admin Approval`;
                    toastTitle.style.color = '#f59e0b';
                    toastDesc.innerHTML = `<strong>${userName}</strong><br><span style="font-size:0.85rem; color:#94a3b8;">${msgDetail}</span>`;
                }

                if (alertBox) {
                    alertBox.style.display = 'block';
                    alertBox.style.background = "rgba(245, 158, 11, 0.25)";
                    alertBox.style.border = "1px solid rgba(245, 158, 11, 0.5)";
                    alertBox.style.color = "#f59e0b";
                    alertBox.innerText = `⏳ ${userName}: ${msgDetail}`;
                }
                if (lastSpokenStatus !== data.status_text) {
                    lastSpokenStatus = data.status_text;
                    speakText(`${userName}, your attendance is pending admin approval.`);
                }
            } else if (data.status_text && data.status_text.startsWith("Cooldown:")) {
                if (toast) toast.style.display = 'none';
                if (alertBox) {
                    alertBox.style.display = 'block';
                    alertBox.style.background = "rgba(245, 158, 11, 0.2)";
                    alertBox.style.border = "1px solid rgba(245, 158, 11, 0.4)";
                    alertBox.style.color = "#f59e0b";
                    alertBox.innerText = `⏳ ${data.status_text}`;
                }
            } else if (data.status_text && data.status_text.startsWith("PROMPT_LOGOUT|")) {
                if (toast) toast.style.display = 'none';
                let promptUser = data.status_text.split("|")[1];
                currentPromptUser = promptUser;
                const logoutModal = document.getElementById('logout-prompt-modal');
                const logoutText = document.getElementById('logout-prompt-text');
                if (logoutModal && logoutModal.style.display !== 'flex') {
                    if (logoutText) logoutText.innerText = `${promptUser}, you are logged in already.. do you want to log out?`;
                    logoutModal.style.display = 'flex';
                }
            } else {
                if (toast) toast.style.display = 'none';
                if (alertBox) alertBox.style.display = 'none';
            }
        } catch (e) { }
    }
    setInterval(pollStatus, 300);

    // --- Logout Prompt Modal Handlers ---
    let currentPromptUser = "";
    const logoutPromptModal = document.getElementById('logout-prompt-modal');
    const closeLogoutPromptBtn = document.getElementById('close-logout-prompt-btn');
    const btnLogoutTesting = document.getElementById('btn-logout-testing');
    const btnLogoutConfirm = document.getElementById('btn-logout-confirm');

    if (closeLogoutPromptBtn) {
        closeLogoutPromptBtn.onclick = () => {
            if (logoutPromptModal) logoutPromptModal.style.display = 'none';
            fetch('/api/clear_prompt', { method: 'POST' });
        };
    }

    if (btnLogoutTesting) {
        btnLogoutTesting.onclick = () => {
            if (logoutPromptModal) logoutPromptModal.style.display = 'none';
            fetch('/api/clear_prompt', { method: 'POST' });
        };
    }

    if (btnLogoutConfirm) {
        btnLogoutConfirm.onclick = async () => {
            if (logoutPromptModal) logoutPromptModal.style.display = 'none';
            if (!currentPromptUser) return;
            
            try {
                const res = await fetch('/api/request_logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_name: currentPromptUser })
                });
                const respData = await res.json();
                
                const alertBox = document.getElementById('side-alert-box');
                if (alertBox) {
                    alertBox.style.display = 'block';
                    alertBox.style.background = "rgba(245, 158, 11, 0.2)";
                    alertBox.style.border = "1px solid rgba(245, 158, 11, 0.4)";
                    alertBox.style.color = "#f59e0b";
                    alertBox.innerText = `⏳ ${currentPromptUser}: Logout request sent to HRM Admin for approval.`;
                }
                speakText(`${currentPromptUser}, your logout request has been sent to HRM Admin for approval.`);
            } catch (err) {
                console.error("Logout request failed:", err);
            }
        };
    }

    function speakText(text) {
        if (!('speechSynthesis' in window)) return;
        window.speechSynthesis.cancel();
        setTimeout(() => {
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.rate = 0.95;
            utterance.pitch = 1.0;
            window.speechSynthesis.speak(utterance);
        }, 100);
    }

    // Admin Auth & Dashboard
    if (openAdminBtn) {
        openAdminBtn.onclick = () => { 
            setSystemState(true); 
            authModal.style.display = 'flex'; 
            passwordInput.value = ''; 
            passwordInput.focus(); 
        };
    }

    if (closeAuthBtn) {
        closeAuthBtn.onclick = () => { setSystemState(false); authModal.style.display = 'none'; };
    }
    if (closeDashBtn) {
        closeDashBtn.onclick = () => { setSystemState(false); dashboardModal.style.display = 'none'; };
    }

    if (submitAuthBtn) {
        submitAuthBtn.onclick = async () => {
            const pwd = passwordInput.value;
            const res = await fetch('/api/admin/verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: pwd })
            });
            const data = await res.json();
            
            if (data.success) {
                authModal.style.display = 'none';
                authError.style.display = 'none';
                dashboardModal.style.display = 'flex';
                loadAdminData();
            } else {
                authError.style.display = 'block';
            }
        };
    }

    async function loadAdminData() {
        try {
            // Load Pending Requests
            const resReqs = await fetch('/api/admin/requests');
            const dataReqs = await resReqs.json();
            const reqsContainer = document.getElementById('pending-requests-container');
            const reqsBody = document.getElementById('requests-tbody');
            const badgeCount = document.getElementById('pending-badge-count');

            if (reqsContainer && reqsBody) {
                reqsBody.innerHTML = '';
                if (dataReqs && dataReqs.length > 0) {
                    reqsContainer.style.display = 'block';
                    if (badgeCount) badgeCount.innerText = dataReqs.length;
                    dataReqs.forEach(req => {
                        reqsBody.innerHTML += `
                            <tr>
                                <td style="font-weight: 700; color: #f8fafc;">${req.user_name}</td>
                                <td>${req.date}</td>
                                <td style="color: #60a5fa; font-weight: 700;">${req.requested_time}</td>
                                <td style="font-size: 0.82rem; color: #cbd5e1;">${req.request_type} &bull; ${req.reason}</td>
                                <td>
                                    <button onclick="handleAdminReqAction('${req.token}', 'approve')" style="background: #10b981; color: white; border: none; padding: 0.35rem 0.7rem; border-radius: 6px; font-weight: 700; cursor: pointer; margin-right: 0.3rem;">✔ Approve</button>
                                    <button onclick="handleAdminReqAction('${req.token}', 'reject')" style="background: #ef4444; color: white; border: none; padding: 0.35rem 0.7rem; border-radius: 6px; font-weight: 700; cursor: pointer;">✖ Reject</button>
                                </td>
                            </tr>
                        `;
                    });
                } else {
                    reqsContainer.style.display = 'none';
                    if (badgeCount) badgeCount.innerText = '0';
                }
            }

            const resUsers = await fetch('/api/admin/users');
            const dataUsers = await resUsers.json();
            const memBody = document.getElementById('members-tbody');
            if (memBody) {
                memBody.innerHTML = '';
                dataUsers.users.forEach(user => {
                    const isObj = typeof user === 'object';
                    const name = isObj ? user.name : user;
                    const emp_id = isObj && user.emp_id ? user.emp_id : 'EMP';
                    const role = isObj && user.role ? user.role : 'Employee';
                    memBody.innerHTML += `
<tr>
    <td>${emp_id}</td>
    <td style="font-weight: 600;">${name}</td>
    <td>${role}</td>
</tr>`;
                });
            }

            const resLogs = await fetch('/api/admin/logs');
            const dataLogs = await resLogs.json();
            const logsBody = document.getElementById('logs-tbody');
            if (logsBody) {
                logsBody.innerHTML = '';
                dataLogs.forEach(log => {
                    logsBody.innerHTML += `<tr>
                        <td>${log.id}</td>
                        <td>${log.user_name}</td>
                        <td>${log.date}</td>
                        <td>${log.login_time}</td>
                        <td>${log.logout_time || '-'}</td>
                        <td>${log.total_hours || '-'}</td>
                    </tr>`;
                });
            }
        } catch (e) { console.error(e); }
    }

    window.handleAdminReqAction = async function(token, action) {
        try {
            const res = await fetch('/api/admin/action_request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: token, action: action })
            });
            const data = await res.json();
            if (data.success) {
                loadAdminData();
            } else {
                alert("Action failed: " + (data.message || "Unknown error"));
            }
        } catch (e) {
            console.error("Action error:", e);
        }
    };
});
