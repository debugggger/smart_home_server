// static/js/notifications.js

class NotificationManager {
    constructor() {
        this.eventSource = null;
        this.isConnected = false;
        this.notifications = [];
        this.maxNotifications = 10;
        this.listeners = [];
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.containerId = 'toastContainer';
        this.counterId = 'toastCounter';
    }

    init() {
        this.createContainer();
        this.connectSSE();
        this.setupAutoReconnect();
    }

    createContainer() {
        if (!document.getElementById(this.containerId)) {
            const container = document.createElement('div');
            container.id = this.containerId;
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        if (!document.getElementById(this.counterId)) {
            const counter = document.createElement('div');
            counter.id = this.counterId;
            counter.className = 'toast-counter';
            counter.style.display = 'none';
            counter.onclick = () => this.showAllToasts();
            document.body.appendChild(counter);
        }
    }

    connectSSE() {
        try {
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }

            const url = '/api/sse/events';
            this.eventSource = new EventSource(url);

            this.eventSource.onopen = () => {
                this.isConnected = true;
                this.reconnectAttempts = 0;
                console.log('✅ SSE уведомления подключены');
                this.updateConnectionStatus('online');
            };

            this.eventSource.onerror = () => {
                this.isConnected = false;
                console.log('❌ SSE уведомления отключены');
                this.updateConnectionStatus('offline');
            };

            this.eventSource.addEventListener('notification', (event) => {
                const data = JSON.parse(event.data);
                this.handleNotification(data);
            });

            this.eventSource.addEventListener('device_updated', (event) => {
                const data = JSON.parse(event.data);
                this.notifyListeners('device_updated', data);
            });

            this.eventSource.addEventListener('device_status_update', (event) => {
                const data = JSON.parse(event.data);
                this.notifyListeners('device_status_update', data);
            });

            this.eventSource.addEventListener('connected', (event) => {
                const data = JSON.parse(event.data);
                console.log('SSE connected:', data);
            });

        } catch (error) {
            console.error('SSE ошибка:', error);
            this.updateConnectionStatus('error');
        }
    }

    setupAutoReconnect() {
        setInterval(() => {
            if (!this.isConnected && this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                console.log(`🔄 Попытка переподключения SSE... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
                this.connectSSE();
            }
        }, 5000);
    }

    handleNotification(data) {
        this.notifications.unshift(data);
        if (this.notifications.length > this.maxNotifications) {
            this.notifications.pop();
        }

        this.showToast(data);
        this.updateCounter();
        this.notifyListeners('notification', data);
    }

    showToast(notification) {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        if (container.children.length >= this.maxNotifications) {
            const lastToast = container.lastElementChild;
            if (lastToast) lastToast.remove();
        }

        const type = notification.type || 'info';
        const message = notification.message || 'Уведомление';
        const details = notification.data || {};

        const toast = document.createElement('div');
        toast.className = `toast type-${type}`;

        const iconMap = {
            'ok': '✅',
            'error': '❌',
            'warning': '⚠️'
        };

        const iconClassMap = {
            'ok': 'ok',
            'error': 'error',
            'warning': 'warning'
        };

        let detailsHtml = '';
        if (details.devices && details.devices.length > 0) {
            detailsHtml = '<div class="toast-details">';
            details.devices.forEach(d => {
                const name = d.device_name || d.name || 'Устройство';
                const typeInfo = d.device_type || d.type || '';
                const port = d.port || '';
                detailsHtml += `• ${name}${typeInfo ? ` (${typeInfo})` : ''}${port ? `, порт: ${port}` : ''}<br>`;
            });
            detailsHtml += '</div>';
        }

        toast.innerHTML = `
            <span class="toast-icon ${iconClassMap[type] || 'info'}">${iconMap[type] || 'ℹ️'}</span>
            <div class="toast-content">
                <div class="toast-message">${this.escapeHtml(message)}</div>
                ${detailsHtml}
            </div>
            <button class="toast-close" onclick="this.closest('.toast').remove(); window.notificationManager.updateCounter();">✕</button>
        `;

        container.prepend(toast);

        if (type === 'ok') {
            setTimeout(() => {
                if (toast.parentNode) toast.remove();
                this.updateCounter();
            }, 5000);
        }

        this.updateCounter();
    }

    updateCounter() {
        const counter = document.getElementById(this.counterId);
        if (!counter) return;

        const unread = this.notifications.filter(n =>
            (n.type === 'error' || n.type === 'warning') && !n.is_read
        ).length;

        if (unread > 0) {
            counter.textContent = unread;
            counter.style.display = 'flex';
        } else {
            counter.style.display = 'none';
        }
    }

    showAllToasts() {
        const container = document.getElementById(this.containerId);
        if (container) {
            container.scrollTop = 0;
        }
        this.notifications.forEach(n => n.is_read = true);
        this.updateCounter();
    }

    updateConnectionStatus(status) {
        const statusDots = document.querySelectorAll('.status-dot');
        const statusTexts = document.querySelectorAll('.status-text');

        statusDots.forEach(dot => {
            dot.className = `status-dot ${status}`;
        });

        const statusMap = {
            'online': 'Подключено',
            'offline': 'Отключено',
            'error': 'Ошибка'
        };

        statusTexts.forEach(text => {
            text.textContent = statusMap[status] || 'Неизвестно';
        });

        this.notifyListeners('connection_status', status);
    }

    addListener(eventType, callback) {
        this.listeners.push({ eventType, callback });
    }

    removeListener(callback) {
        this.listeners = this.listeners.filter(l => l.callback !== callback);
    }

    notifyListeners(eventType, data) {
        this.listeners.forEach(listener => {
            if (listener.eventType === eventType) {
                try {
                    listener.callback(data);
                } catch (error) {
                    console.error('Ошибка в listener:', error);
                }
            }
        });
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    getNotificationHistory(limit = 10) {
        return this.notifications.slice(0, limit);
    }

    clearNotifications() {
        this.notifications = [];
        const container = document.getElementById(this.containerId);
        if (container) container.innerHTML = '';
        this.updateCounter();
    }
}

// Создаем глобальный экземпляр
window.notificationManager = new NotificationManager();

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    window.notificationManager.init();
});